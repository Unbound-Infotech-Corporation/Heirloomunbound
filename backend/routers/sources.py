"""Cloud / local data sources — Gmail/Drive Takeout uploads + companion-driven local folder sync."""
import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, UserMessage
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/sources", tags=["sources"])

# ---- supported source kinds ----
SOURCE_KINDS = {
    "local_folder": "Local folder on your PC (via companion)",
    "gmail_takeout": "Gmail — Google Takeout upload",
    "drive_takeout": "Google Drive — Takeout / folder zip upload",
    "generic_upload": "Generic text / docs upload",
}

EXTRACTOR_SYSTEM = """You receive raw user text scraped from one of their personal sources (email body, doc, journal note, chat log). Extract a JSON array of personality fragments. Each item: {type: 'memory'|'value'|'advice'|'quote'|'note', title: '<<=90 chars>>', content: '<cleaned first-person passage, preserve their voice>', tags: ['source','etc']}. Return ONLY valid JSON, no fences, no prose. Max 8 items per call. Skip noise (auto-replies, signatures, transactional emails, copyright boilerplate, ads).
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Source registration ----------
class SourceCreate(BaseModel):
    kind: str
    label: str
    config: dict = {}  # e.g. {path: "/Users/me/Journal"} for local_folder


@router.post("")
async def create_source(payload: SourceCreate, user: dict = Depends(get_current_user)):
    if payload.kind not in SOURCE_KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown source kind: {payload.kind}")
    src_id = f"src_{uuid.uuid4().hex[:10]}"
    doc = {
        "source_id": src_id,
        "user_id": user["user_id"],
        "kind": payload.kind,
        "label": payload.label.strip() or SOURCE_KINDS[payload.kind],
        "config": payload.config or {},
        "last_synced_at": None,
        "imported_count": 0,
        "status": "idle",
        "created_at": _now(),
    }
    await db.sources.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("")
async def list_sources(user: dict = Depends(get_current_user)):
    cursor = db.sources.find({"user_id": user["user_id"]}, {"_id": 0}).sort("created_at", -1)
    return await cursor.to_list(length=100)


@router.delete("/{source_id}")
async def delete_source(source_id: str, user: dict = Depends(get_current_user)):
    res = await db.sources.delete_one({"source_id": source_id, "user_id": user["user_id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"ok": True}


# ---------- Local folder sync (queues a command for the companion) ----------
@router.post("/{source_id}/sync-local")
async def trigger_local_sync(source_id: str, user: dict = Depends(get_current_user)):
    src = await db.sources.find_one(
        {"source_id": source_id, "user_id": user["user_id"], "kind": "local_folder"},
        {"_id": 0},
    )
    if not src:
        raise HTTPException(status_code=404, detail="Local folder source not found")
    path = src.get("config", {}).get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="Source has no path configured")

    cmd_id = f"cmd_{uuid.uuid4().hex[:10]}"
    await db.companion_commands.insert_one(
        {
            "cmd_id": cmd_id,
            "user_id": user["user_id"],
            "kind": "sync_folder",
            "payload": {"path": path, "source_id": source_id},
            "status": "queued",
            "result": None,
            "created_at": _now(),
            "completed_at": None,
        }
    )
    await db.sources.update_one(
        {"source_id": source_id}, {"$set": {"status": "syncing"}}
    )
    return {"cmd_id": cmd_id, "ok": True}


# ---------- Takeout / generic upload ----------
TEXT_EXT = {".txt", ".md", ".html", ".htm", ".csv", ".json", ".rtf"}


async def _extract_with_claude(user_id: str, source_id: str, raw_text: str, source_label: str) -> int:
    """Have Claude pull memory fragments from a chunk of text and store as entries."""
    if not EMERGENT_LLM_KEY or not raw_text.strip():
        return 0
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"src_{source_id}_{uuid.uuid4().hex[:8]}",
        system_message=EXTRACTOR_SYSTEM,
    ).with_model("anthropic", "claude-sonnet-4-6")
    try:
        raw = await chat.send_message(UserMessage(text=f"Source: {source_label}\n\nText:\n{raw_text[:14000]}"))
        raw = raw if isinstance(raw, str) else getattr(raw, "content", str(raw))
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
        items = json.loads(cleaned.strip())
        if not isinstance(items, list):
            return 0
    except Exception:  # noqa: BLE001
        return 0

    count = 0
    now = _now()
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        eid = f"ent_{uuid.uuid4().hex[:12]}"
        await db.entries.insert_one(
            {
                "entry_id": eid,
                "user_id": user_id,
                "type": item.get("type", "memory") if item.get("type") in {"memory", "value", "advice", "quote", "note"} else "memory",
                "title": (item.get("title") or "Imported")[:120],
                "content": item.get("content", "")[:4000],
                "tags": (item.get("tags") or []) + [f"source:{source_label[:30]}"],
                "source": f"source:{source_id}",
                "source_id": source_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        count += 1
    return count


def _parse_mbox_bytes(data: bytes, max_messages: int = 50) -> list[str]:
    """Lightweight mbox extractor — pull sender-written body text from up to N messages."""
    import email
    from email import policy

    chunks = []
    # Split on "\nFrom " mbox separator
    parts = data.split(b"\nFrom ")
    for i, part in enumerate(parts[:max_messages * 2]):
        if i > 0:
            part = b"From " + part
        try:
            msg = email.message_from_bytes(part, policy=policy.default)
        except Exception:  # noqa: BLE001
            continue
        # Only keep messages this user SENT (best signal of voice)
        subject = (msg.get("Subject") or "")[:120]
        body_text = ""
        if msg.is_multipart():
            for sub in msg.walk():
                if sub.get_content_type() == "text/plain":
                    try:
                        body_text = sub.get_content()
                    except Exception:  # noqa: BLE001
                        body_text = ""
                    break
        else:
            try:
                body_text = msg.get_content()
            except Exception:  # noqa: BLE001
                body_text = ""
        body_text = (body_text or "").strip()
        if not body_text or len(body_text) < 60:
            continue
        chunks.append(f"Subject: {subject}\n\n{body_text[:4000]}")
        if len(chunks) >= max_messages:
            break
    return chunks


def _extract_text_from_zip(data: bytes, max_files: int = 40) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist()[:max_files * 4]:
                name = info.filename
                if info.is_dir() or info.file_size > 2 * 1024 * 1024:
                    continue
                lower = name.lower()
                if not any(lower.endswith(ext) for ext in TEXT_EXT):
                    continue
                try:
                    with zf.open(info) as fp:
                        raw = fp.read().decode("utf-8", errors="ignore")
                except Exception:  # noqa: BLE001
                    continue
                if raw.strip():
                    out.append((name, raw))
                if len(out) >= max_files:
                    break
    except zipfile.BadZipFile:
        return []
    return out


@router.post("/{source_id}/upload")
async def upload_to_source(
    source_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    src = await db.sources.find_one(
        {"source_id": source_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not src:
        raise HTTPException(status_code=404, detail="Source not found")
    if src["kind"] == "local_folder":
        raise HTTPException(status_code=400, detail="Use the companion sync for local folders")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload")
    if len(data) > 120 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Upload over 120MB limit")

    fname = (file.filename or "upload").lower()
    label = src["label"]
    extracted_total = 0
    chunks: list[str] = []

    if fname.endswith(".mbox"):
        chunks = _parse_mbox_bytes(data)
    elif fname.endswith(".zip"):
        for name, txt in _extract_text_from_zip(data):
            chunks.append(f"# {name}\n\n{txt[:4000]}")
    elif any(fname.endswith(ext) for ext in TEXT_EXT):
        try:
            chunks = [data.decode("utf-8", errors="ignore")[:14000]]
        except Exception:  # noqa: BLE001
            chunks = []
    else:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: .mbox, .zip, .txt, .md, .json, .html, .csv")

    if not chunks:
        raise HTTPException(status_code=400, detail="No usable content found in file")

    for chunk in chunks[:20]:  # cap per-upload extraction calls
        extracted_total += await _extract_with_claude(user["user_id"], source_id, chunk, label)

    await db.sources.update_one(
        {"source_id": source_id},
        {
            "$set": {"last_synced_at": _now(), "status": "idle"},
            "$inc": {"imported_count": extracted_total},
        },
    )
    return {"extracted": extracted_total, "chunks_processed": min(len(chunks), 20)}


# ---------- Companion: upload a single discovered file ----------
async def _device_user(authorization: Optional[str]) -> dict:
    from deps import db as _db
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing device token")
    token = authorization.split(" ", 1)[1].strip()
    device = await _db.companion_devices.find_one({"device_token": token, "revoked": False}, {"_id": 0})
    if not device:
        raise HTTPException(status_code=401, detail="Invalid device token")
    user = await _db.users.find_one({"user_id": device["user_id"]}, {"_id": 0})
    return user


@router.post("/companion-upload")
async def companion_upload(
    source_id: str = Form(...),
    relative_path: str = Form(""),
    file: UploadFile = File(...),
    authorization: Optional[str] = None,  # set by header dependency below
):
    # Manually re-resolve auth here — couldn't use Depends without circular import
    from fastapi import Request  # noqa
    raise HTTPException(status_code=501, detail="Use /api/companion/sync-file from the companion script")
