"""Daily compaction job — runs in a worker thread so the UI never blocks.

Pulls turns for a date from the local Vault → ships them to /api/vault/compact
→ ingests the resulting facts via /api/vault/facts/ingest → writes the daily
journal → applies the user's tier policy. Idempotent at the date level.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Callable, List, Optional

import requests
from PySide6.QtCore import QObject, Signal

from . import api, config
from .vault import Vault


@dataclass
class CompactionResult:
    date: str
    turns_seen: int
    facts_extracted: int
    facts_uploaded: int
    facts_skipped: int
    summary: str
    themes: List[str]
    error: Optional[str] = None


class Maintenance(QObject):
    """Run via .run_async(date=None to do all uncompacted)."""

    progress = Signal(str)            # status text for the UI
    completed = Signal(object)        # CompactionResult per day
    finished = Signal(int, int)       # (days_done, days_failed)
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

    def run_async(self, date: Optional[str] = None) -> None:
        def _work() -> dict:
            vault = Vault()
            days = [date] if date else vault.uncompacted_days()
            if not days:
                return {"done": 0, "failed": 0, "results": []}

            settings = config.load_settings()
            tier = settings.get("storage_tier", "partial")
            results: list[CompactionResult] = []
            failed = 0

            for day in days:
                self.progress.emit(f"Compacting {day}…")
                try:
                    r = self._compact_one(vault, day)
                    results.append(r)
                    self.completed.emit(asdict(r))
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    self.progress.emit(f"{day}: failed — {exc}")

            # Apply tier policy ONCE per run, not per day
            self.progress.emit(f"Applying tier '{tier}' policy…")
            vault.apply_tier_policy(tier)

            return {"done": len(results), "failed": failed, "results": results}

        def _on_ok(payload: dict) -> None:
            self.finished.emit(payload.get("done", 0), payload.get("failed", 0))

        def _on_err(msg: str) -> None:
            self.error.emit(msg)
            self.finished.emit(0, 1)

        api._submit(_work, _on_ok, _on_err)  # type: ignore[attr-defined]

    # ---- worker logic ----
    def _compact_one(self, vault: Vault, day: str) -> CompactionResult:
        raw_turns = vault.turns_for_day(day)
        if not raw_turns:
            vault.record_compaction(
                day, turns_seen=0, facts_extracted=0, summary="(no turns)", themes=[],
            )
            return CompactionResult(day, 0, 0, 0, 0, "(no turns)", [])

        payload_turns = [
            {"role": t.role, "text": t.text, "ts": t.ts, "kind": t.kind}
            for t in raw_turns if t.text
        ]

        # 1) ask Claude to extract facts + summary
        url = config.BACKEND_URL.rstrip("/") + "/api/vault/compact"
        headers = {
            "Authorization": f"Bearer {config.DEVICE_TOKEN}",
            "Content-Type": "application/json",
        }
        r = requests.post(
            url,
            json={"date": day, "turns": payload_turns},
            headers=headers,
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"/vault/compact {r.status_code}: {r.text[:200]}")
        comp = r.json()
        facts = comp.get("facts") or []
        summary = comp.get("summary") or ""
        themes = comp.get("themes") or []
        turns_seen = comp.get("turns_seen") or len(payload_turns)

        # 2) ingest facts into cloud memory_facts (this is what makes the twin
        # actually learn — facts here flow into the system prompt of every
        # future twin conversation).
        ingested = 0
        skipped = 0
        if facts:
            ingest_url = config.BACKEND_URL.rstrip("/") + "/api/vault/facts/ingest"
            ir = requests.post(
                ingest_url,
                json={"facts": facts, "date": day},
                headers=headers,
                timeout=30,
            )
            if ir.status_code < 400:
                ij = ir.json()
                ingested = int(ij.get("inserted", 0))
                skipped = int(ij.get("skipped", 0))

        # 3) record the compaction + write daily journal markdown
        vault.record_compaction(
            day,
            turns_seen=turns_seen,
            facts_extracted=ingested,
            summary=summary,
            themes=themes,
        )
        return CompactionResult(
            date=day,
            turns_seen=turns_seen,
            facts_extracted=len(facts),
            facts_uploaded=ingested,
            facts_skipped=skipped,
            summary=summary,
            themes=themes,
        )
