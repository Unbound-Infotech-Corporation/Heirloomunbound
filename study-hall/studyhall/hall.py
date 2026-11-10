"""Library, study room, and the approval gate.

Filing a lesson writes cited study knowledge for the twin.
Accepting an idea writes a receipt only. It never changes the twin's code.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from studyhall.config import load_config, package_root
from studyhall.discover import Seat, assign_panel, discover, practice_panel
from studyhall.embed import keyword_overlap, text_hash
from studyhall.panel import PanelResult, practice_complete, run_study
from studyhall.reader import Reading, extract_html, topic_candidates
from studyhall.store import Store

SAMPLE = package_root() / "sample" / "voice-and-memory.html"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def knowledge_mirrors(store: Store) -> list[Path]:
    mirrors: list[Path] = []
    root = (os.environ.get("HEIRLOOM_DATA_ROOT") or "").strip()
    if root:
        mirrors.append(Path(root) / "study-hall" / "knowledge" / "approved.json")
    explicit = (os.environ.get("HEIRLOOM_STUDY_KNOWLEDGE") or "").strip()
    if explicit:
        mirrors.append(Path(explicit))
    return [path for path in mirrors if path.resolve() != store.knowledge_path.resolve()]


class Hall:
    def __init__(self, root: Path):
        self.store = Store(root)
        from studyhall.missions import ensure_standing

        ensure_standing(self.store)

    def _upsert(self, name: str, key: str, row: dict) -> None:
        items = self.store.read_items(name)
        for index, item in enumerate(items):
            if item.get(key) == row.get(key):
                items[index] = row
                self.store.write_items(name, items)
                return
        items.append(row)
        self.store.write_items(name, items)

    def _get(self, name: str, key: str, value: str) -> dict | None:
        for item in self.store.read_items(name):
            if item.get(key) == value:
                return item
        return None

    def add_reading(self, reading: Reading, *, origin: str = "url") -> dict:
        if reading.status != "ok":
            return {
                "stored": False,
                "status": reading.status,
                "message": reading.message,
                "citation": reading.citation(),
            }
        if reading.kind == "feed":
            row = {
                "source_id": _id("src"),
                "kind": "feed",
                "title": reading.title,
                "url": reading.url,
                "date": reading.date,
                "text": "",
                "items": reading.items,
                "origin": origin,
                "added_at": _now(),
                "text_hash": "",
            }
            self._upsert("library.json", "source_id", row)
            return {"stored": True, "status": "ok", "source": row}

        digest = text_hash(reading.text)
        for existing in self.store.read_items("library.json"):
            if existing.get("text_hash") and existing.get("text_hash") == digest:
                return {
                    "stored": False,
                    "status": "duplicate",
                    "message": "This reading is already in the library.",
                    "source": existing,
                    "citation": reading.citation(),
                }
        row = {
            "source_id": _id("src"),
            "kind": reading.kind,
            "title": reading.title,
            "url": reading.url,
            "date": reading.date,
            "text": reading.text,
            "items": [],
            "origin": origin,
            "added_at": _now(),
            "text_hash": digest,
        }
        self._upsert("library.json", "source_id", row)
        return {"stored": True, "status": "ok", "source": row}

    def add_sample(self) -> dict:
        raw = SAMPLE.read_text(encoding="utf-8")
        extracted = extract_html(raw, "sample://voice-and-memory")
        reading = Reading(
            status="ok",
            url="sample://voice-and-memory",
            title=extracted["title"],
            date=extracted["date"],
            text=extracted["text"],
            kind="article",
        )
        return self.add_reading(reading, origin="sample")

    def library(self) -> list[dict]:
        rows = self.store.read_items("library.json")
        public = []
        for row in rows:
            view = dict(row)
            text = view.get("text") or ""
            view["excerpt"] = text[:280]
            view["words"] = len(text.split())
            view.pop("text", None)
            public.append(view)
        return public

    def source(self, source_id: str) -> dict | None:
        return self._get("library.json", "source_id", source_id)

    def lessons(self) -> list[dict]:
        return self.store.read_items("lessons.json")

    def proposals(self) -> list[dict]:
        return self.store.read_items("proposals.json")

    def receipts(self) -> list[dict]:
        return self.store.read_items("receipts.json")

    def _replace_receipt(self, receipt: dict) -> None:
        items = self.store.read_items("receipts.json")
        for index, item in enumerate(items):
            if item.get("receipt_id") == receipt.get("receipt_id"):
                items[index] = receipt
                self.store.write_items("receipts.json", items)
                return

    def _receipt(self, action: str, target_id: str, summary: str, wrote: list[str], note: str) -> dict:
        receipt = {
            "receipt_id": _id("rcpt"),
            "action": action,
            "target_id": target_id,
            "at": _now(),
            "summary": summary[:300],
            "wrote": wrote,
            "code_changed": False,
            "note": note,
        }
        items = self.store.read_items("receipts.json")
        items.append(receipt)
        self.store.write_items("receipts.json", items)
        return receipt

    def _publish(self) -> list[str]:
        filed = []
        for lesson in self.store.read_items("lessons.json"):
            if lesson.get("status") != "filed":
                continue
            filed.append({
                "lesson_id": lesson["lesson_id"],
                "summary": lesson.get("summary") or "",
                "why_it_matters": lesson.get("why_it_matters") or "",
                "confidence": lesson.get("confidence") or 0,
                "citations": lesson.get("citations") or [],
                "source_url": lesson.get("source_url") or "",
                "source_title": lesson.get("source_title") or "",
                "source_date": lesson.get("source_date") or "",
                "approved_at": lesson.get("approved_at") or "",
                "receipt_id": lesson.get("receipt_id") or "",
                "engine": lesson.get("engine") or "",
                "tag": (lesson.get("tags") or [""])[0] if lesson.get("tags") else "",
            })
        return self.store.publish_knowledge(filed, knowledge_mirrors(self.store))

    async def study(self, source_id: str, *, engine: str = "auto", tag: str = "", focus: str = "", on_note=None) -> dict:
        source = self.source(source_id)
        if source is None:
            raise KeyError(source_id)
        if source.get("kind") == "feed" or not (source.get("text") or "").strip():
            raise ValueError("Open one article, paper, or PDF before running the panel.")
        config = load_config()
        from studyhall.providers import cloud_seats, provider_complete

        extra, cloud_moderator = cloud_seats(self.store.root)
        if engine == "practice":
            readers, moderator = practice_panel(config)
            used = "practice"
        else:
            found = await _found_models()
            readers, moderator = assign_panel(found, config)
            readers = list(readers) + list(extra)
            if cloud_moderator is not None:
                moderator = cloud_moderator
            if not readers or moderator is None:
                raise RuntimeError("no-models")
            used = "local"

        async def complete(seat, messages):
            if seat.kind in {"openai", "gemini"}:
                return await provider_complete(seat, messages, self.store.root)
            if seat.kind == "practice" or used == "practice":
                return await practice_complete(seat, messages)
            return await _ollama_complete(seat, messages)
        filed_titles = [
            str(item.get("source_title") or item.get("summary") or "")
            for item in self.store.read_items("lessons.json")
            if item.get("status") == "filed"
        ]
        result = await run_study(
            source,
            readers,
            moderator,
            complete,
            engine=used,
            already_filed=[title for title in filed_titles if title],
            focus=focus,
            on_note=on_note,
        )
        return self._save_panel(source, result, tag=tag)

    def _save_panel(self, source: dict, result: PanelResult, tag: str = "") -> dict:
        lesson_id = _id("les")
        lesson = {
            "lesson_id": lesson_id,
            "source_id": source.get("source_id") or "",
            "status": "draft",
            "created_at": _now(),
            "tags": [tag] if tag else [],
            **result.lesson,
        }
        self._upsert("lessons.json", "lesson_id", lesson)
        proposals = []
        for raw in result.proposals:
            row = {
                "proposal_id": _id("prop"),
                "lesson_id": lesson_id,
                "source_id": source.get("source_id") or "",
                "status": "pending",
                "created_at": _now(),
                "area": raw["area"],
                "title": raw["title"],
                "idea": raw["idea"],
            }
            proposals.append(row)
            self._upsert("proposals.json", "proposal_id", row)
        notes = [
            {
                "model": note.model,
                "host": note.host,
                "round": note.round,
                "text": note.text,
                "parsed": note.parsed,
            }
            for note in result.notes
        ]
        return {"lesson": lesson, "proposals": proposals, "notes": notes, "engine": result.engine}

    def file_lesson(self, lesson_id: str) -> dict:
        lesson = self._get("lessons.json", "lesson_id", lesson_id)
        if lesson is None:
            raise KeyError(lesson_id)
        if lesson.get("status") == "filed" and lesson.get("receipt_id"):
            receipt = self._get("receipts.json", "receipt_id", lesson["receipt_id"])
            return {"lesson": lesson, "receipt": receipt, "already": True}
        if lesson.get("status") == "rejected":
            raise ValueError("This lesson was set aside. Run the panel again if you want a new card.")
        lesson["status"] = "filed"
        lesson["approved_at"] = _now()
        receipt = self._receipt(
            "file_lesson",
            lesson_id,
            lesson.get("summary") or "",
            ["knowledge/approved.json"],
            "Filed into twin study knowledge. No twin code was modified.",
        )
        lesson["receipt_id"] = receipt["receipt_id"]
        self._upsert("lessons.json", "lesson_id", lesson)
        receipt["wrote"] = self._publish()
        self._replace_receipt(receipt)
        return {"lesson": lesson, "receipt": receipt, "already": False}

    def reject_lesson(self, lesson_id: str) -> dict:
        lesson = self._get("lessons.json", "lesson_id", lesson_id)
        if lesson is None:
            raise KeyError(lesson_id)
        if lesson.get("status") == "filed":
            raise ValueError("This lesson is already filed. Unfile it if you want it out of the twin.")
        lesson["status"] = "rejected"
        self._upsert("lessons.json", "lesson_id", lesson)
        receipt = self._receipt(
            "reject_lesson",
            lesson_id,
            lesson.get("summary") or "",
            ["lessons.json", "receipts.json"],
            "Set aside. Nothing was written into twin knowledge.",
        )
        return {"lesson": lesson, "receipt": receipt}

    def unfile_lesson(self, lesson_id: str) -> dict:
        lesson = self._get("lessons.json", "lesson_id", lesson_id)
        if lesson is None:
            raise KeyError(lesson_id)
        if lesson.get("status") != "filed":
            raise ValueError("This lesson is not filed.")
        lesson["status"] = "draft"
        lesson["approved_at"] = ""
        self._upsert("lessons.json", "lesson_id", lesson)
        receipt = self._receipt(
            "unfile_lesson",
            lesson_id,
            lesson.get("summary") or "",
            ["knowledge/approved.json"],
            "Removed from twin study knowledge. No twin code was modified.",
        )
        lesson["receipt_id"] = receipt["receipt_id"]
        self._upsert("lessons.json", "lesson_id", lesson)
        receipt["wrote"] = self._publish()
        self._replace_receipt(receipt)
        return {"lesson": lesson, "receipt": receipt}

    def accept_proposal(self, proposal_id: str) -> dict:
        """Record the owner's yes. Do not apply the idea to the twin."""
        proposal = self._get("proposals.json", "proposal_id", proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        if proposal.get("status") == "accepted" and proposal.get("receipt_id"):
            receipt = self._get("receipts.json", "receipt_id", proposal["receipt_id"])
            return {"proposal": proposal, "receipt": receipt, "already": True}
        proposal["status"] = "accepted"
        proposal["decided_at"] = _now()
        self._upsert("proposals.json", "proposal_id", proposal)
        receipt = self._receipt(
            "accept_idea",
            proposal_id,
            proposal.get("title") or "",
            ["proposals.json", "receipts.json"],
            "Idea accepted as a decision. The twin's code and settings were not changed.",
        )
        proposal["receipt_id"] = receipt["receipt_id"]
        self._upsert("proposals.json", "proposal_id", proposal)
        return {"proposal": proposal, "receipt": receipt, "already": False}

    def decline_proposal(self, proposal_id: str) -> dict:
        proposal = self._get("proposals.json", "proposal_id", proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        proposal["status"] = "declined"
        proposal["decided_at"] = _now()
        self._upsert("proposals.json", "proposal_id", proposal)
        receipt = self._receipt(
            "decline_idea",
            proposal_id,
            proposal.get("title") or "",
            ["proposals.json", "receipts.json"],
            "Idea declined. Nothing was changed.",
        )
        proposal["receipt_id"] = receipt["receipt_id"]
        self._upsert("proposals.json", "proposal_id", proposal)
        return {"proposal": proposal, "receipt": receipt}

    def related_titles(self, text: str, limit: int = 3) -> list[str]:
        scored = []
        for lesson in self.store.read_items("lessons.json"):
            if lesson.get("status") != "filed":
                continue
            blob = " ".join([
                str(lesson.get("summary") or ""),
                str(lesson.get("why_it_matters") or ""),
                str(lesson.get("source_title") or ""),
            ])
            score = keyword_overlap(text, blob)
            if score:
                scored.append((score, str(lesson.get("source_title") or lesson.get("summary") or "")))
        scored.sort(key=lambda item: -item[0])
        return [title for _score, title in scored[:limit] if title]


async def _found_models():
    report = await discover(load_config())
    from studyhall.discover import FoundModel

    found = []
    for host in report["hosts"]:
        if not host.get("ok"):
            continue
        for name in host.get("models") or []:
            found.append(FoundModel(name, host["url"].rstrip("/"), host["name"], host.get("kind") or "ollama"))
    return found


async def _ollama_complete(seat: Seat, messages: list[dict]) -> str:
    import httpx

    timeout = httpx.Timeout(180.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        if seat.kind == "ollama":
            response = await client.post(
                seat.endpoint.rstrip("/") + "/api/chat",
                json={"model": seat.model, "messages": messages, "stream": False, "options": {"temperature": 0.2}},
            )
            response.raise_for_status()
            payload = response.json()
            return str((payload.get("message") or {}).get("content") or "")
        response = await client.post(
            seat.endpoint.rstrip("/") + "/v1/chat/completions",
            json={"model": seat.model, "messages": messages, "temperature": 0.2},
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content") or "")


async def lookup_topic(client, topic: str) -> dict:
    return await topic_candidates(client, topic)
