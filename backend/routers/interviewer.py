"""AI Interviewer: streaming Claude chat that asks deep personality questions."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from emergentintegrations.llm.chat import LlmChat, StreamDone, TextDelta, UserMessage
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deps import EMERGENT_LLM_KEY, db, get_current_user

router = APIRouter(prefix="/interviewer", tags=["interviewer"])

INTERVIEWER_SYSTEM = """You are a warm, patient, deeply curious biographer interviewing the user so that their voice, stories, values, and personality can live on for their children, grandchildren, and loved ones long after they are gone.

Your role:
- Ask ONE meaningful question at a time. Never bundle multiple questions.
- Move between life chapters (childhood, family, work, love, fears, regrets, joys, beliefs, lessons, hopes for descendants).
- Listen carefully to each answer. Reference earlier details in follow-ups so the user feels truly heard.
- Be gentle with grief, mortality, and family wounds. Never push past discomfort.
- When the user gives a short answer, follow up with a specific, vivid question (the smell, the room, the day, the person's exact words) to draw out detail.
- Occasionally summarize what you've learned ("So your father's quiet patience shaped the way you parent — is that fair?") to confirm memory accuracy.
- Avoid clinical phrasing. Avoid "As an AI...". Speak like a thoughtful interviewer in a slow conversation across a kitchen table.

Open with a brief, grounded greeting and ONE opening question. Then continue from there based on the user's responses."""


SEED_QUESTIONS = [
    "If your grandchild asked you what your childhood home felt like — the smells, the sounds, the people moving through it — what would you tell them first?",
    "Who taught you what love looks like, and what's one specific moment that proves it?",
    "What is a belief you held strongly at 25 that you've since let go of, and what changed your mind?",
    "Tell me about a time you were truly afraid — and what (or who) helped you through it.",
    "What is the piece of advice you most want your son to remember when life gets hard?",
    "What song, smell, or place could bring you to tears in an instant, and what story sits behind it?",
    "Describe the kind of father you tried to be. Where did you succeed? Where do you wish you'd done differently?",
    "What's a small, unimportant memory that has stayed with you for no clear reason?",
    "If we sat at your kitchen table 30 years from now, what would you want the room to smell like?",
    "What do you want to be forgiven for, by whom?",
]


class ChatTurn(BaseModel):
    role: str
    content: str


class StartRequest(BaseModel):
    conversation_id: Optional[str] = None


class MessageRequest(BaseModel):
    conversation_id: str
    message: str
    save_as_memory: bool = Field(default=False)


@router.get("/seed-questions")
async def get_seed_questions(user: dict = Depends(get_current_user)):
    return {"questions": SEED_QUESTIONS}


@router.post("/start")
async def start_conversation(payload: StartRequest, user: dict = Depends(get_current_user)):
    if payload.conversation_id:
        conv = await db.conversations.find_one(
            {"conversation_id": payload.conversation_id, "user_id": user["user_id"]},
            {"_id": 0},
        )
        if conv:
            return conv

    conversation_id = f"conv_{uuid.uuid4().hex[:12]}"
    doc = {
        "conversation_id": conversation_id,
        "user_id": user["user_id"],
        "kind": "interviewer",
        "messages": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.conversations.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    cursor = db.conversations.find(
        {"user_id": user["user_id"], "kind": "interviewer"}, {"_id": 0}
    ).sort("updated_at", -1)
    return await cursor.to_list(length=50)


async def _gather_user_context(user_id: str, max_entries: int = 30) -> str:
    cursor = db.entries.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(max_entries)
    entries = await cursor.to_list(length=max_entries)
    if not entries:
        return ""
    parts = ["Here is what you already know about this person from their archive (for context — do not repeat back, just let it inform your questions):\n"]
    for e in entries:
        parts.append(f"- [{e['type']}] {e['title']}: {e['content'][:280]}")
    return "\n".join(parts)


@router.post("/message")
async def send_message(payload: MessageRequest, user: dict = Depends(get_current_user)):
    conv = await db.conversations.find_one(
        {"conversation_id": payload.conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    context = await _gather_user_context(user["user_id"])
    system_message = INTERVIEWER_SYSTEM + ("\n\n" + context if context else "")

    # Session ID = conversation_id so emergentintegrations preserves context across turns
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=payload.conversation_id,
        system_message=system_message,
    ).with_model("anthropic", "claude-sonnet-4-6")

    user_turn = {"role": "user", "content": payload.message, "ts": datetime.now(timezone.utc).isoformat()}

    async def event_generator():
        full = ""
        try:
            async for ev in chat.stream_message(UserMessage(text=payload.message)):
                if isinstance(ev, TextDelta):
                    full += ev.content
                    yield f"data: {ev.content}\n\n".replace("\n\n", "\n\n")
                elif isinstance(ev, StreamDone):
                    break
        except Exception as exc:  # noqa: BLE001
            yield f"event: error\ndata: {exc!s}\n\n"
            return

        assistant_turn = {
            "role": "assistant",
            "content": full,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        await db.conversations.update_one(
            {"conversation_id": payload.conversation_id},
            {
                "$push": {"messages": {"$each": [user_turn, assistant_turn]}},
                "$set": {"updated_at": datetime.now(timezone.utc).isoformat()},
            },
        )
        if payload.save_as_memory:
            entry_id = f"ent_{uuid.uuid4().hex[:12]}"
            await db.entries.insert_one({
                "entry_id": entry_id,
                "user_id": user["user_id"],
                "type": "memory",
                "title": payload.message[:80],
                "content": payload.message,
                "tags": ["interviewer"],
                "source": "interviewer",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/conversation/{conversation_id}")
async def get_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    conv = await db.conversations.find_one(
        {"conversation_id": conversation_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.post("/save-turn")
async def save_turn_as_entry(
    payload: dict,
    user: dict = Depends(get_current_user),
):
    """Persist a single Q+A turn from the interviewer chat as a structured archive entry."""
    title = payload.get("title") or (payload.get("question") or "Interview moment")[:100]
    content_parts = []
    if payload.get("question"):
        content_parts.append(f"Q: {payload['question']}")
    if payload.get("answer"):
        content_parts.append(f"A: {payload['answer']}")
    content = "\n\n".join(content_parts) if content_parts else (payload.get("content") or "")

    entry_id = f"ent_{uuid.uuid4().hex[:12]}"
    doc = {
        "entry_id": entry_id,
        "user_id": user["user_id"],
        "type": payload.get("type", "memory"),
        "title": title,
        "content": content,
        "tags": payload.get("tags", ["interviewer"]),
        "source": "interviewer",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.entries.insert_one(doc)
    doc.pop("_id", None)
    return doc
