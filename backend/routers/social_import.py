"""Social/text data import — paste raw text, optionally have AI extract structured entries."""
import json
import uuid
from datetime import datetime, timezone

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
    source: str  # facebook | twitter | reddit | blog | discord | other
    raw_text: str
    auto_extract: bool = True


@router.post("")
async def import_text(payload: ImportRequest, user: dict = Depends(get_current_user)):
    if not payload.raw_text.strip():
        raise HTTPException(status_code=400, detail="raw_text is empty")

    import_id = f"imp_{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "import_id": import_id,
        "user_id": user["user_id"],
        "source": payload.source,
        "raw_text": payload.raw_text[:200000],
        "created_at": now,
        "extracted_count": 0,
    }
    extracted: list[dict] = []

    if payload.auto_extract and EMERGENT_LLM_KEY:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=import_id,
            system_message=EXTRACTOR_SYSTEM,
        ).with_model("anthropic", "claude-sonnet-4-6")
        try:
            response = await chat.send_message(
                UserMessage(text=f"Source: {payload.source}\n\nRaw text:\n{payload.raw_text[:18000]}")
            )
            raw = response if isinstance(response, str) else getattr(response, "content", str(response))
            # Strip code fences if any slipped through
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
                if cleaned.endswith("```"):
                    cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
            items = json.loads(cleaned) if cleaned else []
            if not isinstance(items, list):
                items = []
            for item in items[:12]:
                if not isinstance(item, dict):
                    continue
                entry_id = f"ent_{uuid.uuid4().hex[:12]}"
                doc = {
                    "entry_id": entry_id,
                    "user_id": user["user_id"],
                    "type": item.get("type", "memory"),
                    "title": (item.get("title") or "Imported")[:120],
                    "content": item.get("content", ""),
                    "tags": item.get("tags", []) + [payload.source, "imported"],
                    "source": f"import:{payload.source}",
                    "import_id": import_id,
                    "created_at": now,
                    "updated_at": now,
                }
                await db.entries.insert_one(doc)
                doc.pop("_id", None)
                extracted.append(doc)
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
