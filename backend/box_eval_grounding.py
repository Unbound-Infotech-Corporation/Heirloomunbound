"""Grounding eval for the twin. Run on the box: heirloom-box eval-grounding

Asks varied questions about the owner's life that no card answers, first with the
owner's current cards and then with one unrelated labeled card approved. Every
answer must decline or cite a real card. Then it checks that normal chat, the
reminder path, and recall of the approved card still work.

Everything it creates is labeled and removed at the end: the card, its vault entry,
the prompt, conversations, episodes, reminders, the session, and lab rows.
Local models only. Nothing is sent to Odysseus or the web.
"""
from __future__ import annotations

import json
import statistics
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from box_selftest import Api, _db

LABEL = "heirloom-eval"
CARD_TITLE = f"{LABEL} first car"
CARD_STORY = "My first car was a blue 1978 Chevy Nova I bought for $800."

LIFE_QUESTIONS = [
    "What was my mom's name?",
    "What did my dad teach me?",
    "Where did I go to high school?",
    "What was my first job?",
    "Who was my best friend growing up?",
    "What's my favorite food?",
    "How did I meet my wife?",
    "What song did we dance to at our wedding?",
    "Where did we go on our honeymoon?",
    "What street did I grow up on?",
    "Tell me about grandpa.",
    "What did I do in the army?",
    "Do you remember our trip to the lake?",
    "What was the hardest year of my life?",
    "What was our family dog called?",
    "Tell me about the house I grew up in.",
]
MULTI_TURN = [
    "What was my first car?",
    "What song did we dance to at my wedding?",
    "Where did I grow up?",
    "What was my first job?",
    "And what was my mom like?",
]
RECALL = [
    "What was my first car?",
    "What was the first thing I ever drove?",
    "Tell me about my old Chevy.",
]
OVERBLOCK = [
    "Hi, how are you today?",
    "Help me write a short birthday note for my sister.",
    "How do I get trout to bite in cold water?",
    "My printer won't connect to wifi. What should I try?",
    "Plan my week: gym three times and a dentist visit.",
    "What's 15% of 80?",
    "I'm going home now.",
]
REMINDER = "Remind me to water the tomato plants tomorrow at 9am"
# Any fixed zone works. The check is that 9am lands on that zone's clock, not UTC.
REMINDER_ZONE = "America/New_York"
# Desktop sends this zone on one turn, then a reminder with no zone must use it.
DESKTOP_ZONE = "America/Chicago"
BIRTHDAY = "Help me write a short birthday note for my sister."
DESKTOP_LIFE = "What was my mom's name?"

_DECLINE = (
    "don't have that memory",
    "don't have a memory",
    "don't remember",
    "do not remember",
    "do not have that memory",
    "no memory of",
)


def declined(text: str) -> bool:
    folded = " ".join((text or "").lower().replace("\u2019", "'").split())
    return any(phrase in folded for phrase in _DECLINE)


def helpful(text: str) -> bool:
    raw = " ".join((text or "").split())
    return len(raw) >= 12 and not declined(raw)


def mentions_card(text: str) -> bool:
    folded = (text or "").lower()
    return "chevy" in folded or "nova" in folded


def embellished_words(text: str) -> list[str]:
    """Content words in the answer that are not on the card. A rough padding gauge."""
    from memory_cards import _content_tokens

    extra = _content_tokens(text) - _content_tokens(CARD_STORY + " " + CARD_TITLE)
    allowed = {"drove", "drive", "owned", "car", "bought", "remember", "written", "here", "have", "down", "dollars"}
    return sorted(word for word in extra if word not in allowed)


class EvalApi(Api):
    def start(self) -> str:
        status, started = self._json("POST", "/api/twin/start", {})
        if status >= 400:
            raise RuntimeError(f"twin start {status}: {started}")
        return str(started.get("conversation_id") or "")

    def say(self, conversation_id: str, question: str, timezone_name: str = "") -> dict[str, Any]:
        sent: dict[str, str] = {"conversation_id": conversation_id, "message": question}
        if timezone_name:
            sent["timezone"] = timezone_name
        request = urllib.request.Request(
            self.base + "/api/twin/message",
            data=json.dumps(sent).encode("utf-8"),
            method="POST",
            headers=self._headers(),
        )
        body = ""
        seconds = 0.0
        for _attempt in range(40):
            began = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    body = response.read().decode("utf-8", errors="replace")
                seconds = time.perf_counter() - began
                break
            except urllib.error.HTTPError as exc:
                # Twin chat allows 20 turns a minute. Wait instead of failing the eval.
                if exc.code != 429:
                    raise
                time.sleep(float(exc.headers.get("Retry-After") or 3) if exc.headers else 3)
        else:
            raise RuntimeError("twin chat stayed rate limited")
        text = ""
        why: list[dict] = []
        brain: dict = {}
        action: dict = {}
        error = ""
        event = ""
        for line in body.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
                continue
            if not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if event == "why" and isinstance(chunk, dict):
                why = list(chunk.get("why") or [])
            elif event == "brain" and isinstance(chunk, dict):
                brain = chunk
            elif event == "action" and isinstance(chunk, dict):
                action = chunk
            elif event == "error" and isinstance(chunk, dict):
                error = str(chunk.get("error") or "")
            elif isinstance(chunk, dict) and chunk.get("text"):
                text += str(chunk["text"])
            event = ""
        return {"text": text, "why": why, "brain": brain, "action": action, "error": error, "seconds": seconds}

    def desktop(self, text: str, timezone_name: str = "") -> dict[str, Any]:
        """One WinUI-style /desktop/chat twin turn."""
        sent: dict[str, Any] = {"text": text, "mode": "twin", "audience": "owner"}
        if timezone_name:
            sent["timezone"] = timezone_name
        status, payload = 429, {}
        seconds = 0.0
        for _attempt in range(40):
            began = time.perf_counter()
            status, payload = self._json("POST", "/api/desktop/chat", sent, timeout=180)
            seconds = time.perf_counter() - began
            if status != 429:
                break
            time.sleep(3)
        if status >= 400:
            return {"text": "", "why": [], "action": {}, "error": f"{status}: {payload}", "seconds": seconds}
        return {
            "text": str(payload.get("reply") or ""),
            "why": list(payload.get("why") or []),
            "action": dict(payload.get("action") or {}),
            "error": "",
            "seconds": seconds,
        }

    def ask_page(self, question: str) -> dict:
        status, payload = self._json("POST", "/api/memory-loop/ask", {"question": question}, timeout=120)
        if status >= 400:
            raise RuntimeError(f"ask {status}: {payload}")
        return payload


def _short(text: str, size: int = 110) -> str:
    raw = " ".join((text or "").split())
    return raw if len(raw) <= size else raw[: size - 1] + "\u2026"


def cleanup(db: Any, user_id: str, card_ids: list[str], prompt_ids: list[str], conversation_ids: list[str],
            reminder_ids: list[str], token: str, started_iso: str) -> None:
    for card_id in card_ids:
        db.memory_cards.delete_many({"user_id": user_id, "card_id": card_id})
        db.entries.delete_many({"user_id": user_id, "card_id": card_id})
    db.memory_cards.delete_many({"user_id": user_id, "title": {"$regex": LABEL}})
    db.entries.delete_many({"user_id": user_id, "title": {"$regex": LABEL}})
    for prompt_id in prompt_ids:
        db.daily_prompts.delete_many({"user_id": user_id, "prompt_id": prompt_id})
    db.daily_prompts.delete_many({"user_id": user_id, "key": {"$in": [LABEL, "heirloom-selftest"]}})
    for conversation_id in conversation_ids:
        db.conversations.delete_many({"user_id": user_id, "conversation_id": conversation_id})
        db.memory_episodes.delete_many({"user_id": user_id, "conversation_id": conversation_id})
    for reminder_id in reminder_ids:
        db.reminders.delete_many({"user_id": user_id, "reminder_id": reminder_id})
    db.reminders.delete_many({"user_id": user_id, "text": "water the tomato plants", "created_at": {"$gte": started_iso}})
    if token:
        db.user_sessions.delete_many({"session_token": token})
    try:
        from lab_mode import drop_selftest_turns

        drop_selftest_turns()
    except Exception:  # noqa: BLE001
        pass


def run() -> int:
    from session_renew import issue

    db = _db()
    user = db.users.find_one({"audience": "owner"}, {"_id": 0})
    if not user:
        print("FAIL no owner user on this box")
        return 1
    user_id = str(user["user_id"])
    now = datetime.now(timezone.utc)
    started_iso = now.isoformat()
    issued = issue(now)
    db.user_sessions.insert_one(issued.document(user_id, now))
    api = EvalApi("http://127.0.0.1:8001", issued.session_token)
    card_ids: list[str] = []
    prompt_ids: list[str] = []
    conversations: list[str] = []
    reminder_ids: list[str] = []
    checks: list[tuple[str, bool]] = []
    latencies: list[float] = []
    invented: dict[str, list[str]] = {}
    # Desktop turns write to the shared companion conversation, the owner's style
    # notes, and the saved zone. They are put back exactly as they were.
    saved_zone = user.get("last_timezone")
    companion_before = {
        str(doc["conversation_id"]): doc
        for doc in db.conversations.find({"user_id": user_id, "kind": "companion_twin"}, {"_id": 0})
    }
    style_before = db.owner_style.find_one({"user_id": user_id}, {"_id": 0})

    def life_round(name: str, real_ids: set[str]) -> None:
        bad: list[str] = []
        for question in LIFE_QUESTIONS:
            conversation_id = api.start()
            conversations.append(conversation_id)
            got = api.say(conversation_id, question)
            latencies.append(got["seconds"])
            cited_real = any(str(row.get("card_id") or "") in real_ids for row in got["why"])
            ok = not got["error"] and (declined(got["text"]) or cited_real)
            if not ok:
                bad.append(question)
            print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  {question} -> {_short(got['text'] or got['error'])}")
        invented[name] = bad
        checks.append((f"{name}: invented {len(bad)} of {len(LIFE_QUESTIONS)}", not bad))

    try:
        approved_real = list(db.memory_cards.find(
            {"user_id": user_id, "status": "approved", "title": {"$not": {"$regex": LABEL}}},
            {"_id": 0, "card_id": 1},
        ))
        real_ids = {str(row.get("card_id") or "") for row in approved_real}
        print(f"Owner cards approved before the eval: {len(real_ids)}")
        print(f"Life questions with {len(real_ids)} owner card(s):")
        life_round(f"life questions with {len(real_ids)} owner cards", real_ids)

        saved = api.answer(f"{CARD_STORY}", "What was your first car?")
        card = saved.get("card") or {}
        prompt = saved.get("prompt") or {}
        card_id = str(card.get("card_id") or "")
        card_ids.append(card_id)
        prompt_ids.append(str(prompt.get("prompt_id") or card.get("prompt_id") or ""))
        status, approved = api._json(
            "PATCH",
            f"/api/memory-loop/cards/{card_id}",
            {"approve": True, "title": CARD_TITLE, "story": CARD_STORY, "era": "1978"},
        )
        if status >= 400:
            raise RuntimeError(f"approve {status}: {approved}")

        print("Life questions with one unrelated card (the car) approved:")
        life_round("life questions with one unrelated card", real_ids)

        print("One conversation, car first, then life questions:")
        conversation_id = api.start()
        conversations.append(conversation_id)
        multi_bad: list[str] = []
        for index, question in enumerate(MULTI_TURN):
            got = api.say(conversation_id, question)
            latencies.append(got["seconds"])
            if index == 0:
                ok = mentions_card(got["text"]) and any(r.get("card_id") == card_id for r in got["why"])
                checks.append(("multi-turn: the car is answered first", ok))
            else:
                ok = declined(got["text"]) and not got["error"]
                if not ok:
                    multi_bad.append(question)
            print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  {question} -> {_short(got['text'] or got['error'])}")
        checks.append((f"multi-turn: invented {len(multi_bad)} of {len(MULTI_TURN) - 1}", not multi_bad))

        print("Recall of the approved card, with citations:")
        for question in RECALL:
            conversation_id = api.start()
            conversations.append(conversation_id)
            got = api.say(conversation_id, question)
            latencies.append(got["seconds"])
            cited = any(r.get("card_id") == card_id for r in got["why"])
            extra = embellished_words(got["text"])
            ok = mentions_card(got["text"]) and cited and not got["error"]
            checks.append((f"recall: {question}", ok))
            print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  cited={cited} extra={extra}  {question} -> {_short(got['text'] or got['error'])}")
        page = api.ask_page("What was my first car?")
        checks.append(("ask page answers the car", mentions_card(str(page.get("reply") or ""))))
        page_job = api.ask_page("What was my first job?")
        checks.append(("ask page declines the first job", declined(str(page_job.get("reply") or ""))))
        print(f"  ask page: car -> {_short(str(page.get('reply')))} | job -> {_short(str(page_job.get('reply')))}")

        print("Normal chat must still help (over-blocking):")
        for question in OVERBLOCK:
            conversation_id = api.start()
            conversations.append(conversation_id)
            got = api.say(conversation_id, question)
            latencies.append(got["seconds"])
            ok = helpful(got["text"]) and not got["error"]
            checks.append((f"helps: {question}", ok))
            print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  {question} -> {_short(got['text'] or got['error'])}")

        print("A reminder is created, not just promised:")
        conversation_id = api.start()
        conversations.append(conversation_id)
        got = api.say(conversation_id, REMINDER, timezone_name=REMINDER_ZONE)
        reminder_id = str((got["action"] or {}).get("reminder_id") or "")
        if reminder_id:
            reminder_ids.append(reminder_id)
        row = db.reminders.find_one({"user_id": user_id, "reminder_id": reminder_id}, {"_id": 0}) if reminder_id else None
        ok = False
        due = str((row or {}).get("due_at") or "")
        if due:
            from zoneinfo import ZoneInfo

            local = datetime.fromisoformat(due).astimezone(ZoneInfo(REMINDER_ZONE))
            ok = local.hour == 9 and local.minute == 0
        checks.append((f"reminder: saved for 9:00 AM {REMINDER_ZONE}", ok))
        print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  due_at={(row or {}).get('due_at')} -> {_short(got['text'])}")

        print("A birthday note keeps its greeting (3 tries):")
        kept = 0
        for _try in range(3):
            conversation_id = api.start()
            conversations.append(conversation_id)
            got = api.say(conversation_id, BIRTHDAY)
            latencies.append(got["seconds"])
            ok = "birthday" in got["text"].lower() and helpful(got["text"]) and not got["error"]
            kept += 1 if ok else 0
            print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  {_short(got['text'], 220)}")
        checks.append((f"birthday note keeps 'birthday' {kept} of 3", kept == 3))

        print("Desktop twin chat (WinUI /desktop/chat) is grounded and keeps the last zone:")
        got = api.desktop(DESKTOP_LIFE, timezone_name=DESKTOP_ZONE)
        latencies.append(got["seconds"])
        ok = declined(got["text"]) and not got["error"]
        checks.append(("desktop: life question declined", ok))
        print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  {DESKTOP_LIFE} -> {_short(got['text'] or got['error'])}")
        stored = (db.users.find_one({"user_id": user_id}, {"_id": 0, "last_timezone": 1}) or {}).get("last_timezone")
        checks.append((f"desktop: zone saved ({stored})", stored == DESKTOP_ZONE))
        got = api.desktop(REMINDER)
        latencies.append(got["seconds"])
        reminder_id = str((got["action"] or {}).get("reminder_id") or "")
        if reminder_id:
            reminder_ids.append(reminder_id)
        row = db.reminders.find_one({"user_id": user_id, "reminder_id": reminder_id}, {"_id": 0}) if reminder_id else None
        ok = False
        due = str((row or {}).get("due_at") or "")
        if due:
            from zoneinfo import ZoneInfo

            local = datetime.fromisoformat(due).astimezone(ZoneInfo(DESKTOP_ZONE))
            ok = local.hour == 9 and local.minute == 0
        checks.append((f"desktop: reminder with no zone saved for 9:00 AM {DESKTOP_ZONE}", ok))
        print(f"  {'ok ' if ok else 'BAD'} {got['seconds']:5.1f}s  due_at={due} -> {_short(got['text'] or got['error'])}")
    except Exception as exc:  # noqa: BLE001
        checks.append((f"eval ran without an error ({exc})", False))
    finally:
        time.sleep(3)  # let style notes and summaries started by the turns finish
        for doc in db.conversations.find({"user_id": user_id, "kind": "companion_twin"}, {"_id": 0}):
            conversation_key = str(doc["conversation_id"])
            if conversation_key in companion_before:
                db.conversations.replace_one(
                    {"user_id": user_id, "conversation_id": conversation_key}, companion_before[conversation_key],
                )
                db.memory_episodes.delete_many({
                    "user_id": user_id, "conversation_id": conversation_key, "created_at": {"$gte": started_iso},
                })
            else:
                conversations.append(conversation_key)
        if style_before is None:
            db.owner_style.delete_many({"user_id": user_id})
        else:
            db.owner_style.replace_one({"user_id": user_id}, style_before, upsert=True)
        if saved_zone:
            db.users.update_one({"user_id": user_id}, {"$set": {"last_timezone": saved_zone}})
        else:
            db.users.update_one({"user_id": user_id}, {"$unset": {"last_timezone": ""}})
        cleanup(db, user_id, card_ids, prompt_ids, conversations, reminder_ids, issued.session_token, started_iso)
        left = {
            "cards": db.memory_cards.count_documents({"user_id": user_id, "title": {"$regex": LABEL}}),
            "conversations": db.conversations.count_documents({"conversation_id": {"$in": conversations}}),
            "reminders": db.reminders.count_documents({"reminder_id": {"$in": reminder_ids}}) if reminder_ids else 0,
        }
        checks.append((f"cleanup left nothing {left}", not any(left.values())))

    failed = 0
    print("")
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
        failed += 0 if ok else 1
    if latencies:
        ordered = sorted(latencies)
        p90 = ordered[max(0, int(round(0.9 * len(ordered))) - 1)]
        print(f"latency: {len(ordered)} turns, median {statistics.median(ordered):.1f}s, p90 {p90:.1f}s, max {ordered[-1]:.1f}s")
    print("PASS" if failed == 0 else f"FAIL {failed}")
    return 0 if failed == 0 else 1


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
