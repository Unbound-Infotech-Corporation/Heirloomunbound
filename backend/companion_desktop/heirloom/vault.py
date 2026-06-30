"""Local Vault — stores every conversation turn (and optionally raw audio)
under the user's chosen folder on their own machine. SQLite for metadata +
flat files for audio. Lives entirely outside the cloud — your data, your disk.

Schema (vault.db, SQLite):
  turns(id, conv_id, role, text, ts, kind, audio_path, compacted_in)
  compactions(date, ran_at, turns_seen, facts_extracted, summary, themes_json)
  audit(id, ts, action, detail)

Storage tiers control what we KEEP after a date is compacted:
  - "full"    : keep everything forever
  - "partial" : delete raw audio older than 30 days; keep transcripts forever
  - "lite"    : the day after compaction, delete raw turns + audio; keep only
                the per-day summary in compactions

All three tiers ALWAYS upload extracted facts to the cloud — that's the
permanent knowledge layer for the twin. Local pruning never affects the twin's
remembered facts.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from . import config


@dataclass
class Turn:
    turn_id: str
    conv_id: str
    role: str
    text: str
    ts: str
    kind: str  # "chat" | "voice"
    audio_path: Optional[str]
    compacted_in: Optional[str]


def vault_root() -> Path:
    """Honours the user's chosen folder; falls back to a Documents subfolder."""
    settings = config.load_settings()
    custom = settings.get("vault_folder")
    if custom:
        p = Path(custom).expanduser()
    else:
        # Documents/HeirloomVault on Windows; ~/HeirloomVault on Mac/Linux
        import os
        if os.name == "nt":
            docs = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
            p = docs / "HeirloomVault"
        else:
            p = Path.home() / "HeirloomVault"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Vault:
    """Single-process SQLite wrapper. Cheap to instantiate."""

    def __init__(self, root: Optional[Path] = None):
        self.root = root or vault_root()
        self.db_path = self.root / "vault.db"
        self.raw_dir = self.root / "raw"
        self.raw_dir.mkdir(exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.db_path))
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def _init_schema(self) -> None:
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS turns (
                    turn_id     TEXT PRIMARY KEY,
                    conv_id     TEXT NOT NULL,
                    role        TEXT NOT NULL,
                    text        TEXT NOT NULL,
                    ts          TEXT NOT NULL,
                    kind        TEXT NOT NULL,
                    audio_path  TEXT,
                    compacted_in TEXT,
                    day         TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS turns_day_idx ON turns(day);
                CREATE INDEX IF NOT EXISTS turns_compacted_idx ON turns(compacted_in);

                CREATE TABLE IF NOT EXISTS compactions (
                    date         TEXT PRIMARY KEY,
                    ran_at       TEXT NOT NULL,
                    turns_seen   INTEGER NOT NULL,
                    facts_extracted INTEGER NOT NULL,
                    summary      TEXT,
                    themes_json  TEXT
                );

                CREATE TABLE IF NOT EXISTS audit (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts      TEXT NOT NULL,
                    action  TEXT NOT NULL,
                    detail  TEXT
                );
            """)

    # ---- writes ----
    def append_turn(
        self,
        conv_id: str,
        role: str,
        text: str,
        *,
        kind: str = "chat",
        audio_bytes: Optional[bytes] = None,
        ts: Optional[str] = None,
    ) -> str:
        ts = ts or _now_iso()
        turn_id = f"t_{uuid.uuid4().hex[:14]}"
        day = ts[:10]
        audio_path = None
        if audio_bytes:
            day_dir = self.raw_dir / day / "audio"
            day_dir.mkdir(parents=True, exist_ok=True)
            audio_path = str(day_dir / f"{turn_id}.wav")
            Path(audio_path).write_bytes(audio_bytes)
        with self._conn() as c:
            c.execute(
                "INSERT INTO turns(turn_id, conv_id, role, text, ts, kind, audio_path, day) VALUES (?,?,?,?,?,?,?,?)",
                (turn_id, conv_id, role, text or "", ts, kind, audio_path, day),
            )
            c.execute(
                "INSERT INTO audit(ts, action, detail) VALUES (?,?,?)",
                (ts, f"append_{kind}_{role}", json.dumps({"turn_id": turn_id, "len": len(text or "")})),
            )
        return turn_id

    # ---- reads ----
    def turns_for_day(self, day: str) -> List[Turn]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM turns WHERE day = ? ORDER BY ts ASC", (day,)
            ).fetchall()
        return [
            Turn(
                turn_id=r["turn_id"],
                conv_id=r["conv_id"],
                role=r["role"],
                text=r["text"],
                ts=r["ts"],
                kind=r["kind"],
                audio_path=r["audio_path"],
                compacted_in=r["compacted_in"],
            )
            for r in rows
        ]

    def uncompacted_days(self) -> List[str]:
        """All days that have turns but no compaction row yet, excluding today."""
        today = _today_str()
        with self._conn() as c:
            rows = c.execute(
                "SELECT DISTINCT day FROM turns WHERE day != ? "
                "AND day NOT IN (SELECT date FROM compactions) ORDER BY day ASC",
                (today,),
            ).fetchall()
        return [r["day"] for r in rows]

    def last_compaction(self) -> Optional[dict]:
        with self._conn() as c:
            r = c.execute(
                "SELECT * FROM compactions ORDER BY ran_at DESC LIMIT 1"
            ).fetchone()
        return dict(r) if r else None

    def storage_usage(self) -> dict:
        """Cheap stat — sum of vault.db + raw/* on disk."""
        total = 0
        files = 0
        for f in self.root.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
                files += 1
        with self._conn() as c:
            turn_count = c.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
            comp_count = c.execute("SELECT COUNT(*) FROM compactions").fetchone()[0]
        return {
            "bytes": total,
            "files": files,
            "turns": turn_count,
            "compactions": comp_count,
            "root": str(self.root),
        }

    # ---- compaction bookkeeping ----
    def record_compaction(
        self,
        date: str,
        *,
        turns_seen: int,
        facts_extracted: int,
        summary: str,
        themes: List[str],
    ) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO compactions(date, ran_at, turns_seen, facts_extracted, summary, themes_json) "
                "VALUES (?,?,?,?,?,?)",
                (date, _now_iso(), turns_seen, facts_extracted, summary, json.dumps(themes)),
            )
            c.execute(
                "UPDATE turns SET compacted_in = ? WHERE day = ?",
                (date, date),
            )
            c.execute(
                "INSERT INTO audit(ts, action, detail) VALUES (?,?,?)",
                (_now_iso(), "compaction", json.dumps({"date": date, "turns": turns_seen, "facts": facts_extracted})),
            )
        # Write a human-readable daily journal
        try:
            day_dir = self.root / "journals"
            day_dir.mkdir(exist_ok=True)
            (day_dir / f"{date}.md").write_text(
                f"# {date}\n\n"
                f"_Compacted at {_now_iso()} — {turns_seen} turns → {facts_extracted} facts learned._\n\n"
                f"## Summary\n\n{summary}\n\n"
                f"## Themes\n\n" + "\n".join(f"- {t}" for t in themes) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass

    # ---- tier policy ----
    def apply_tier_policy(self, tier: str, *, today: Optional[str] = None) -> dict:
        """
        - full    : no-op (keep everything)
        - partial : delete raw audio files older than 30 days
        - lite    : for any COMPACTED day older than today, drop turn rows + audio
        """
        today = today or _today_str()
        deleted_files = 0
        deleted_turns = 0

        if tier == "full":
            pass
        elif tier == "partial":
            cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            with self._conn() as c:
                rows = c.execute(
                    "SELECT turn_id, audio_path FROM turns WHERE day < ? AND audio_path IS NOT NULL",
                    (cutoff,),
                ).fetchall()
                for r in rows:
                    p = r["audio_path"]
                    if p:
                        try:
                            Path(p).unlink(missing_ok=True)
                            deleted_files += 1
                        except OSError:
                            pass
                c.execute(
                    "UPDATE turns SET audio_path = NULL WHERE day < ? AND audio_path IS NOT NULL",
                    (cutoff,),
                )
        elif tier == "lite":
            with self._conn() as c:
                # Wipe turn rows + audio for every day that's already compacted
                comp_days = [r["date"] for r in c.execute(
                    "SELECT date FROM compactions WHERE date < ?", (today,),
                ).fetchall()]
                for day in comp_days:
                    rows = c.execute(
                        "SELECT audio_path FROM turns WHERE day = ? AND audio_path IS NOT NULL",
                        (day,),
                    ).fetchall()
                    for r in rows:
                        try:
                            Path(r["audio_path"]).unlink(missing_ok=True)
                            deleted_files += 1
                        except OSError:
                            pass
                    res = c.execute("DELETE FROM turns WHERE day = ?", (day,))
                    deleted_turns += res.rowcount or 0
                # Drop the now-empty day directories
                for d in (self.raw_dir).iterdir():
                    if d.is_dir() and d.name in comp_days:
                        try:
                            # Only remove if empty (audio sub-dir is the only child)
                            for sub in d.iterdir():
                                if sub.is_dir() and not any(sub.iterdir()):
                                    sub.rmdir()
                            if not any(d.iterdir()):
                                d.rmdir()
                        except OSError:
                            pass

        with self._conn() as c:
            c.execute(
                "INSERT INTO audit(ts, action, detail) VALUES (?,?,?)",
                (_now_iso(), "tier_policy", json.dumps({
                    "tier": tier, "deleted_files": deleted_files, "deleted_turns": deleted_turns,
                })),
            )
        return {"deleted_files": deleted_files, "deleted_turns": deleted_turns}
