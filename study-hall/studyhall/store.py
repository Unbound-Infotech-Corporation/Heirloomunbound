"""JSON files on this PC. Writes stay inside the Study Hall data directory."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.knowledge_path = self.root / "knowledge" / "approved.json"

    def path_for(self, name: str) -> Path:
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("invalid store name")
        dest = (self.root / name).resolve()
        root = self.root.resolve()
        if dest != root and root not in dest.parents:
            raise ValueError("invalid store name")
        return dest

    def read_items(self, name: str) -> list[dict]:
        loaded = self._read(self.path_for(name))
        items = loaded.get("items") if isinstance(loaded, dict) else None
        if not isinstance(items, list):
            return []
        return [row for row in items if isinstance(row, dict)]

    def write_items(self, name: str, items: list[dict]) -> None:
        self._atomic(self.path_for(name), {"items": items})

    def read_settings(self) -> dict:
        loaded = self._read(self.path_for("settings.json"))
        return loaded if isinstance(loaded, dict) else {}

    def write_settings(self, settings: dict) -> None:
        self._atomic(self.path_for("settings.json"), settings)

    def publish_knowledge(self, lessons: list[dict], mirrors: list[Path] | None = None) -> list[str]:
        """Replace the twin's approved-study file. Only this shape is published."""
        payload = {"lessons": lessons}
        self._atomic(self.knowledge_path, payload)
        wrote = ["knowledge/approved.json"]
        for mirror in mirrors or []:
            try:
                target = Path(mirror)
                if target.resolve() == self.knowledge_path.resolve():
                    continue
                self._atomic(target, payload)
                wrote.append(str(target))
            except OSError:
                continue
        return wrote

    def read_knowledge(self) -> list[dict]:
        loaded = self._read(self.knowledge_path)
        lessons = loaded.get("lessons") if isinstance(loaded, dict) else None
        if not isinstance(lessons, list):
            return []
        return [row for row in lessons if isinstance(row, dict)]

    def _read(self, path: Path) -> dict:
        if not path.is_file():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8") or "null")
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _atomic(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
