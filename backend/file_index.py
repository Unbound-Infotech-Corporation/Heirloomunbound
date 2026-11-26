"""Local file search: an SQLite FTS5 index of folders the owner picks.

Nothing is indexed until the owner adds a folder. Only text is read (plain
text, Markdown, CSV, HTML, PDF, Word .docx); other files are findable by name.
Keys, wallets, password stores, and dot-folders are never opened. The index is
a file on this machine; nothing about it leaves the box.

    python file_index.py add /srv/family-docs
    python file_index.py reindex
    python file_index.py search "furnace warranty"
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".rtf", ".html", ".htm", ".xml", ".yaml", ".yml", ".ini"}
DOC_EXT = {".pdf", ".docx"}
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_TEXT_CHARS = 400_000
MAX_FILES = 50_000
SKIP_DIRS = {"node_modules", "__pycache__", "appdata", "$recycle.bin", "system volume information", "venv", ".venv", "site-packages"}
_SECRET_NAME = re.compile(
    r"(^\.env|\.pem$|\.key$|\.p12$|\.pfx$|\.kdbx$|^id_(rsa|ed25519|ecdsa)|wallet|password|passwd|secret|credential|\.ovpn$|\.gpg$|\.asc$|\.pass$|\.sqlite$|\.db$|token)",
    re.I,
)


def data_dir() -> Path:
    raw = os.environ.get("HEIRLOOM_DATA_DIR", "").strip()
    if raw:
        return Path(raw)
    if Path("/var/lib/heirloom").is_dir():
        return Path("/var/lib/heirloom")
    return Path.home() / ".heirloom"


def index_path() -> Path:
    raw = os.environ.get("HEIRLOOM_FILE_INDEX", "").strip()
    return Path(raw) if raw else data_dir() / "skills" / "file-index.sqlite"


_BLOCKED_ROOTS = ("/", "/etc", "/proc", "/sys", "/dev", "/run", "/root", "/boot", "/usr", "/bin", "/sbin", "/lib", "/var")


def allowed_root(root: str) -> bool:
    """Folders of documents, not the system or Heirloom's own data (sealed keys live there)."""
    resolved = Path(root).expanduser().resolve()
    text = str(resolved).replace("\\", "/").rstrip("/") or "/"
    low = text.lower()
    if text in _BLOCKED_ROOTS or low.startswith(("/proc", "/sys", "/dev", "/etc", "/run", "/boot")):
        return False
    heirloom = str(data_dir().resolve()).replace("\\", "/").rstrip("/").lower()
    if low == heirloom or (low.startswith(heirloom + "/") and not low.startswith(heirloom + "/files")):
        return False
    if re.match(r"^[a-z]:/?$", low) or re.match(r"^[a-z]:/(windows|program files|programdata)", low):
        return False
    return True


def secret_like(path: Path) -> bool:
    return bool(_SECRET_NAME.search(path.name))


def skip_dir(name: str) -> bool:
    low = name.lower()
    return low.startswith(".") or low in SKIP_DIRS


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    return re.sub(r"<[^>]+>", " ", text)


def _docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader  # optional

        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:200])
    except ImportError:
        pass
    import shutil
    import subprocess

    exe = shutil.which("pdftotext")
    if not exe:
        return ""
    done = subprocess.run([exe, "-l", "200", str(path), "-"], capture_output=True, timeout=60)
    return done.stdout.decode("utf-8", "ignore")


def extract_text(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext in TEXT_EXT:
            raw = path.read_bytes()[: MAX_TEXT_CHARS * 2].decode("utf-8", "ignore")
            return _strip_html(raw) if ext in {".html", ".htm", ".xml"} else raw
        if ext == ".docx":
            return _docx_text(path)
        if ext == ".pdf":
            return _pdf_text(path)
    except Exception:  # noqa: BLE001 - an unreadable file is indexed by name only
        return ""
    return ""


@dataclass
class Hit:
    path: str
    name: str
    snippet: str
    modified: float


class FileIndex:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else index_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS roots (root TEXT PRIMARY KEY, added REAL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
        self.db.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(path UNINDEXED, name, body, tokenize='porter unicode61')"
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # roots
    def roots(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT root FROM roots ORDER BY root")]

    def add_root(self, root: str) -> str:
        resolved = str(Path(root).expanduser().resolve())
        if not Path(resolved).is_dir():
            raise ValueError(f"Not a folder: {root}")
        if not allowed_root(resolved):
            raise ValueError(f"{root} is a system or Heirloom data folder; pick a folder of documents.")
        self.db.execute("INSERT OR IGNORE INTO roots VALUES (?, ?)", (resolved, time.time()))
        self.db.commit()
        return resolved

    def remove_root(self, root: str) -> int:
        resolved = str(Path(root).expanduser().resolve())
        self.db.execute("DELETE FROM roots WHERE root = ?", (resolved,))
        gone = [r[0] for r in self.db.execute("SELECT path FROM files WHERE path LIKE ?", (resolved + "%",))]
        self._drop(gone)
        self.db.commit()
        return len(gone)

    def _drop(self, paths: Iterable[str]) -> None:
        for p in paths:
            self.db.execute("DELETE FROM files WHERE path = ?", (p,))
            self.db.execute("DELETE FROM docs WHERE path = ?", (p,))

    def walk(self, root: str) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not skip_dir(d)]
            for name in filenames:
                path = Path(dirpath) / name
                if name.startswith(".") or secret_like(path):
                    continue
                yield path

    def reindex(self, *, max_files: int = MAX_FILES) -> dict:
        started = time.perf_counter()
        known = {row[0]: (row[1], row[2]) for row in self.db.execute("SELECT path, mtime, size FROM files")}
        seen: set[str] = set()
        added = updated = 0
        for root in self.roots():
            for path in self.walk(root):
                if len(seen) >= max_files:
                    break
                try:
                    st = path.stat()
                except OSError:
                    continue
                key = str(path)
                seen.add(key)
                if known.get(key) == (st.st_mtime, st.st_size):
                    continue
                body = "" if st.st_size > MAX_FILE_BYTES else extract_text(path)[:MAX_TEXT_CHARS]
                self._drop([key])
                self.db.execute("INSERT INTO files VALUES (?, ?, ?)", (key, st.st_mtime, st.st_size))
                self.db.execute("INSERT INTO docs VALUES (?, ?, ?)", (key, path.name, body))
                if key in known:
                    updated += 1
                else:
                    added += 1
        removed = [p for p in known if p not in seen]
        self._drop(removed)
        self.db.commit()
        return {
            "files": len(seen),
            "added": added,
            "updated": updated,
            "removed": len(removed),
            "ms": int((time.perf_counter() - started) * 1000),
        }

    def count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def search(self, query: str, *, limit: int = 8) -> list[Hit]:
        words = re.findall(r"[\w']+", query or "", flags=re.UNICODE)
        words = [w for w in words if len(w) > 1]
        if not words:
            return []
        match = " OR ".join(f'"{w}"*' for w in words[:12])
        rows = self.db.execute(
            "SELECT d.path, d.name, snippet(docs, 2, '[', ']', ' … ', 18), f.mtime "
            "FROM docs d JOIN files f ON f.path = d.path WHERE docs MATCH ? ORDER BY bm25(docs, 0.0, 4.0, 1.0) LIMIT ?",
            (match, max(1, min(limit, 25))),
        ).fetchall()
        return [Hit(path=r[0], name=r[1], snippet=" ".join((r[2] or "").split()), modified=r[3]) for r in rows]


async def exec_search_files(user_id: str, args: dict, *, index: Optional[FileIndex] = None) -> dict:
    import asyncio

    query = str(args.get("query") or "").strip()
    if not query:
        return {"summary": "No search words given.", "ui": {"count": 0}}

    def _run() -> tuple[list[Hit], int]:
        idx = index or FileIndex()
        try:
            if not idx.roots():
                return [], -1
            return idx.search(query, limit=int(args.get("limit") or 6)), idx.count()
        finally:
            if index is None:
                idx.close()

    hits, total = await asyncio.to_thread(_run)
    if total < 0:
        return {
            "summary": "File search is not set up: no folders are indexed. The owner can add folders in Settings > Skills.",
            "ui": {"count": 0, "error": "not_connected"},
        }
    if not hits:
        return {"summary": f"No indexed files match '{query}' ({total} files indexed).", "ui": {"count": 0}}
    lines = [f"{len(hits)} file(s) match '{query}':"]
    for h in hits:
        when = time.strftime("%Y-%m-%d", time.localtime(h.modified))
        lines.append(f"- {h.name} ({h.path}, modified {when}): {h.snippet[:240]}")
    return {"summary": "\n".join(lines), "ui": {"count": len(hits), "paths": [h.path for h in hits]}}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"add", "remove", "reindex", "search", "status"}:
        print(__doc__)
        return 2
    idx = FileIndex()
    try:
        cmd = argv[0]
        if cmd == "add":
            for root in argv[1:]:
                print("added", idx.add_root(root))
            print(json.dumps(idx.reindex()))
        elif cmd == "remove":
            for root in argv[1:]:
                print("removed", idx.remove_root(root), "files")
        elif cmd == "reindex":
            print(json.dumps(idx.reindex()))
        elif cmd == "status":
            print(json.dumps({"roots": idx.roots(), "files": idx.count(), "index": str(idx.path)}))
        else:
            for h in idx.search(" ".join(argv[1:])):
                print(f"{h.path}\n    {h.snippet}")
    finally:
        idx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
