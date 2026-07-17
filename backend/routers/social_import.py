"""Social/text data import — paste raw text, optionally have AI extract structured entries.

Also supports deterministic parsers for WhatsApp chat exports and SMS dumps
so large message logs become archive entries without relying solely on the LLM.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/import", tags=["import"])

EXTRACTOR_SYSTEM = """You receive raw social media exports / pasted text from a person.
Extract a JSON array of personality fragments. Each item must have:
  - type: one of "memory", "value", "advice", "quote", "story"
  - title: a short, evocative title (max 90 chars)
  - content: the cleaned, first-person passage (preserve their voice)
  - tags: array of short tags
Return ONLY valid JSON. No prose, no markdown fences. If nothing useful is found, return [].
Maximum 12 items per call. Skip junk (likes counts, timestamps without context, generic shares).
"""


class ImportRequest(BaseModel):
    source: str  # facebook | twitter | reddit | blog | discord | whatsapp | sms | other
    raw_text: str
    auto_extract: bool = True


def _attr(attrs: str, name: str) -> str:
    m = re.search(rf'\b{re.escape(name)}="([^"]*)"', attrs, flags=re.I)
    if m:
        return m.group(1)
    m = re.search(rf"\b{re.escape(name)}='([^']*)'", attrs, flags=re.I)
    return m.group(1) if m else ""


def parse_sms_export(raw: str, filename: str = "") -> list[dict[str, Any]]:
    """Parse SMS Backup & Restore XML or plain text message dumps."""
    out: list[dict[str, Any]] = []
    text = raw or ""
    if "<sms" in text.lower() or text.lstrip().startswith("<?xml"):
        for m in re.finditer(
            r'<sms\b([^>]*)>(?:[^<]*)</sms>|<sms\b([^/]*)/>',
            text,
            flags=re.I,
        ):
            attrs = m.group(1) or m.group(2) or ""
            body = _attr(attrs, "body")
            if not body:
                continue
            addr = _attr(attrs, "address")
            date_ms = _attr(attrs, "date")
            date = None
            if date_ms.isdigit():
                try:
                    date = datetime.utcfromtimestamp(int(date_ms) / 1000.0).isoformat() + "Z"
                except Exception:
                    date = None
            out.append(
                {
                    "type": "story",
                    "title": f"SMS with {addr}" if addr else "SMS",
                    "content": body.strip(),
                    "tags": ["sms", "imported"],
                    "date": date,
                    "people": [addr] if addr else [],
                }
            )
        if out:
            return out

    blocks = re.split(r"\n(?=From:\s)", text, flags=re.I)
    for block in blocks:
        if not block.strip():
            continue
        from_m = re.search(r"^From:\s*(.+)$", block, re.M | re.I)
        date_m = re.search(r"^Date:\s*(.+)$", block, re.M | re.I)
        body = re.sub(r"^(From|Date|To|Subject):\s*.+$", "", block, flags=re.M | re.I).strip()
        if len(body) < 3:
            continue
        who = (from_m.group(1).strip() if from_m else "") or "SMS"
        out.append(
            {
                "type": "story",
                "title": f"SMS — {who[:80]}",
                "content": body[:8000],
                "tags": ["sms", "imported"],
                "date": (date_m.group(1).strip() if date_m else None),
                "people": [who] if from_m else [],
            }
        )
    return out


def parse_whatsapp_export(raw: str, filename: str = "") -> list[dict[str, Any]]:
    """
    Parse WhatsApp chat export (.txt).
    Formats:
      [DD/MM/YYYY, HH:MM:SS] Name: message
      DD/MM/YYYY, HH:MM - Name: message
      M/D/YY, H:MM AM/PM - Name: message
    """
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        ln
        for ln in text.split("\n")
        if ln.strip()
        and "Messages and calls are end-to-end encrypted" not in ln
        and "end-to-end encrypted" not in ln.lower()
    ]
    pattern = re.compile(
        r"^"
        r"(?:\u200e|\u200f)?"
        r"(?:\[?)?"
        r"(?P<date>\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4})"
        r",?\s+"
        r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)"
        r"(?:\]|\s+-)\s*"
        r"(?P<name>[^:]+):\s*"
        r"(?P<body>.*)$",
        re.I,
    )
    messages: list[tuple[str, str, str, str]] = []
    cur_date = cur_time = cur_name = ""
    cur_body: list[str] = []

    def flush():
        nonlocal cur_body
        body = "\n".join(cur_body).strip()
        if not cur_name or not body:
            return
        if body.startswith("<Media omitted>") or body == "This message was deleted":
            return
        messages.append((cur_date, cur_time, cur_name.strip(), body))

    for ln in lines:
        m = pattern.match(ln.strip())
        if m:
            flush()
            cur_date = m.group("date")
            cur_time = m.group("time")
            cur_name = m.group("name")
            cur_body = [m.group("body") or ""]
        elif cur_name:
            cur_body.append(ln)
    flush()

    if not messages:
        return []

    out: list[dict[str, Any]] = []
    chunk_size = 40
    for i in range(0, len(messages), chunk_size):
        chunk = messages[i : i + chunk_size]
        people = sorted({n for _, _, n, _ in chunk})
        lines_out = [f"[{d} {t}] {n}: {b}" for d, t, n, b in chunk]
        first = chunk[0]
        title_people = ", ".join(people[:3])
        if len(people) > 3:
            title_people += f" +{len(people) - 3}"
        out.append(
            {
                "type": "story",
                "title": f"WhatsApp — {title_people}"[:120],
                "content": "\n".join(lines_out)[:12000],
                "tags": ["whatsapp", "imported", "chat"],
                "date": f"{first[0]} {first[1]}".strip() or None,
                "people": people[:20],
                "meta": {
                    "kind": "whatsapp",
                    "message_count": len(chunk),
                    "source_file": filename or "",
                },
            }
        )
    return out


async def _persist_items(
    user_id: str,
    import_id: str,
    source: str,
    items: list[dict],
    now: str,
    *,
    max_items: int = 40,
) -> list[dict]:
    extracted: list[dict] = []
    for item in items[:max_items]:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if len(content) < 3:
            continue
        entry_id = f"ent_{uuid.uuid4().hex[:12]}"
        tags = list(item.get("tags") or [])
        if source not in tags:
            tags.append(source)
        if "imported" not in tags:
            tags.append("imported")
        doc = {
            "entry_id": entry_id,
            "user_id": user_id,
            "type": item.get("type", "memory"),
            "title": (item.get("title") or "Imported")[:120],
            "content": content,
            "tags": tags,
            "source": f"import:{source}",
            "import_id": import_id,
            "created_at": item.get("date") or now,
            "updated_at": now,
        }
        if item.get("people"):
            doc["people"] = item["people"]
        if item.get("meta"):
            doc["meta"] = item["meta"]
        await db.entries.insert_one(doc)
        doc.pop("_id", None)
        extracted.append(doc)
    return extracted


@router.post("")
async def import_text(payload: ImportRequest, user: dict = Depends(get_current_user)):
    from routers.executor_lock import assert_writable

    await assert_writable(user["user_id"])
    if not payload.raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text is empty")

    source = (payload.source or "other").strip().lower()
    import_id = f"imp_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "import_id": import_id,
        "user_id": user["user_id"],
        "source": source,
        "raw_text": payload.raw_text[:200000],
        "created_at": now,
        "extracted_count": 0,
    }
    extracted: list[dict] = []

    # Deterministic parsers for chat dumps (preferred over LLM for fidelity)
    parsed: list[dict] = []
    if source == "whatsapp":
        parsed = parse_whatsapp_export(payload.raw_text)
    elif source == "sms":
        parsed = parse_sms_export(payload.raw_text)

    if parsed:
        extracted = await _persist_items(
            user["user_id"], import_id, source, parsed, now, max_items=60
        )
        record["parser"] = source
    elif payload.auto_extract and EMERGENT_LLM_KEY:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=import_id,
            system_message=EXTRACTOR_SYSTEM,
        ).with_model("anthropic", "claude-sonnet-4-6")
        try:
            response = await chat.send_message(
                UserMessage(text=f"Source: {source}\n\nRaw text:\n{payload.raw_text[:18000]}")
            )
            raw = response if isinstance(response, str) else getattr(response, "content", str(response))
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
            items = json.loads(cleaned) if cleaned else []
            if not isinstance(items, list):
                items = []
            extracted = await _persist_items(
                user["user_id"], import_id, source, items, now, max_items=12
            )
        except Exception as exc:  # noqa: BLE001
            record["extract_error"] = str(exc)

    record["extracted_count"] = len(extracted)
    await db.imports.insert_one(record)

    return {"import_id": import_id, "extracted": extracted, "count": len(extracted)}


@router.get("")
async def list_imports(user: dict = Depends(get_current_user)):
    cursor = db.imports.find({"user_id": user["user_id"]}, {"_id": 0, "raw_text": 0}).sort(
        "created_at", -1
    )
    return await cursor.to_list(length=100)
