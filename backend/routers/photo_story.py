"""Photo → Story — drop in a photo, the twin looks at it, asks a few personal
questions, then weaves your answers into a first-person memory filed in your
archive. A rich, low-effort way to grow the personality behind the twin.
"""
from __future__ import annotations

import base64
import io
import json
import uuid
from datetime import datetime, timezone

from emergentintegrations.llm.chat import ImageContent, LlmChat, StreamDone, TextDelta, UserMessage
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/photo-story", tags=["photo-story"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _vision_json(image_b64: str) -> dict:
    """Look at the photo → a short scene description + 3 warm, specific questions."""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"ps_{uuid.uuid4().hex[:8]}",
        system_message=(
            "You help someone turn a personal photo into a written memory for their family archive. "
            "Look closely at the photo. Respond ONLY with strict JSON of the form "
            '{"description": "<one warm sentence describing what you see>", '
            '"questions": ["<q1>", "<q2>", "<q3>"]}. '
            "The questions must be personal and specific to THIS photo (who's in it, where/when it might be, "
            "what was happening, how it felt) — the kind a thoughtful biographer would ask to draw out the story. "
            "No preamble, no markdown."
        ),
    ).with_model("anthropic", "claude-sonnet-4-6")
    text = ""
    async for ev in chat.stream_message(
        UserMessage(text="Describe this photo and ask three questions.", file_contents=[ImageContent(image_base64=image_b64)])
    ):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, StreamDone):
            break
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(text)
        desc = str(data.get("description", "")).strip()
        qs = [str(q).strip() for q in (data.get("questions") or []) if str(q).strip()][:3]
    except Exception:  # noqa: BLE001
        desc, qs = "", []
    if not qs:
        qs = [
            "Who is in this photo, and what do they mean to you?",
            "Where and roughly when was this taken?",
            "What do you remember most about this moment?",
        ]
    return {"description": desc, "questions": qs}


@router.post("/start")
async def start(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image")
    # Downscale to keep the doc small and vision fast.
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if img.width > 1400:
            img = img.resize((1400, int(img.height * 1400 / img.width)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        raw = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Couldn't read image: {exc!s}") from exc

    image_b64 = base64.b64encode(raw).decode("ascii")
    ps_id = f"ps_{uuid.uuid4().hex[:12]}"
    try:
        vision = await _vision_json(image_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Vision failed: {exc!s}") from exc

    await db.photo_stories.insert_one({
        "photo_story_id": ps_id,
        "user_id": user["user_id"],
        "image_b64": image_b64,
        "mime": "image/jpeg",
        "description": vision["description"],
        "questions": vision["questions"],
        "status": "draft",
        "created_at": _now(),
    })
    return {
        "photo_story_id": ps_id,
        "description": vision["description"],
        "questions": vision["questions"],
        "image_url": f"/api/photo-story/{ps_id}/image",
    }


@router.get("/{ps_id}/image")
async def image(ps_id: str, user: dict = Depends(get_current_user)):
    doc = await db.photo_stories.find_one({"photo_story_id": ps_id, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return Response(
        content=base64.b64decode(doc["image_b64"]),
        media_type=doc.get("mime", "image/jpeg"),
        headers={"Cache-Control": "private, max-age=86400"},
    )


class ComposeReq(BaseModel):
    answers: list[str] = []


@router.post("/{ps_id}/compose")
async def compose(ps_id: str, payload: ComposeReq, user: dict = Depends(get_current_user)):
    doc = await db.photo_stories.find_one({"photo_story_id": ps_id, "user_id": user["user_id"]}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")

    qa_pairs = []
    for q, a in zip(doc.get("questions", []), payload.answers):
        if str(a).strip():
            qa_pairs.append(f"Q: {q}\nA: {a.strip()}")
    qa_blob = "\n\n".join(qa_pairs) or "(the person didn't add details — write from the photo alone)"

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"psc_{ps_id}",
        system_message=(
            "You are a warm, faithful ghostwriter helping someone preserve a memory for their family. "
            "Using the photo description and their answers, write the memory in FIRST PERSON ('I', 'we') "
            "as the person themselves, in their natural voice — 120–220 words, evocative but honest, no clichés, "
            "no invented facts beyond what's given. Start with a compelling opening line. "
            "Return strict JSON: {\"title\": \"<short evocative title>\", \"story\": \"<the memory>\"}. No markdown."
        ),
    ).with_model("anthropic", "claude-sonnet-4-6")
    prompt = f"Photo: {doc.get('description', '')}\n\nTheir answers:\n{qa_blob}"
    text = ""
    async for ev in chat.stream_message(UserMessage(text=prompt)):
        if isinstance(ev, TextDelta):
            text += ev.content
        elif isinstance(ev, StreamDone):
            break
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(text)
        title = str(data.get("title", "")).strip() or "A photo I kept"
        story = str(data.get("story", "")).strip()
    except Exception:  # noqa: BLE001
        title, story = "A photo I kept", text
    if not story:
        raise HTTPException(status_code=502, detail="Couldn't compose the story")

    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    now = _now()
    await db.entries.insert_one({
        "entry_id": entry_id,
        "user_id": user["user_id"],
        "type": "story",
        "title": title,
        "content": story,
        "tags": ["photo"],
        "audio_url": None,
        "source": "photo_story",
        "photo_story_id": ps_id,
        "created_at": now,
        "updated_at": now,
    })
    await db.photo_stories.update_one(
        {"photo_story_id": ps_id}, {"$set": {"status": "filed", "entry_id": entry_id}}
    )
    return {"entry_id": entry_id, "title": title, "content": story}
