"""Owner check for the memory loop. Creates one labeled card, asks it, then deletes it.

Run on the box: heirloom-box selftest
That executes this module inside the API container.
"""
from __future__ import annotations

import json
import math
import os
import struct
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

LABEL = "heirloom-selftest"
STORY = "My first car was a blue Chevy I drove when I was young."
DIRECT = "What was my first car?"
PARAPHRASE = "What did I drive when I was young?"
UNKNOWN = "What was my dog named?"


def tone_wav() -> bytes:
    rate = 16000
    buffer = BytesIO()
    with wave.open(buffer, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(4000 * math.sin(2 * math.pi * 220 * i / rate)))
            for i in range(rate)
        )
        handle.writeframes(frames)
    return buffer.getvalue()


def mentions_car(text: str) -> bool:
    folded = (text or "").lower()
    return "chevy" in folded or "first car" in folded


def declines(text: str) -> bool:
    folded = (text or "").lower()
    return "don't have that memory yet" in folded or "don't have an approved memory" in folded


def judge(direct: str, paraphrase: str, chat_direct: str, chat_paraphrase: str, unknown: str, heard: bool) -> list[tuple[str, bool]]:
    return [
        ("ask page answers the car directly", mentions_car(direct)),
        ("ask page answers the paraphrase", mentions_car(paraphrase)),
        ("twin chat answers the car directly", mentions_car(chat_direct)),
        ("twin chat answers the paraphrase", mentions_car(chat_paraphrase)),
        ("an unknown memory is declined", declines(unknown) and "ford" not in unknown.lower()),
        ("hearing accepts a recording", heard),
    ]


def report(rows: list[tuple[str, bool]]) -> int:
    failed = 0
    for name, ok in rows:
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            failed += 1
    print("PASS" if failed == 0 else f"FAIL {failed}")
    return 0 if failed == 0 else 1


class Api:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def _json(self, method: str, path: str, body: dict | None = None, timeout: float = 60) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw or "{}")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw or "{}")
            except json.JSONDecodeError:
                payload = {"detail": raw}
            return exc.code, payload

    def answer(self, transcript: str, question: str) -> dict:
        status, payload = self._json("POST", "/api/memory-loop/answer", {
            "transcript": transcript,
            "question": question,
            "key": LABEL,
        })
        if status >= 400:
            raise RuntimeError(f"answer {status}: {payload}")
        return payload

    def approve(self, card_id: str) -> dict:
        status, payload = self._json("PATCH", f"/api/memory-loop/cards/{card_id}", {"approve": True})
        if status >= 400:
            raise RuntimeError(f"approve {status}: {payload}")
        return payload

    def ask(self, question: str) -> str:
        status, payload = self._json("POST", "/api/memory-loop/ask", {"question": question}, timeout=40)
        if status >= 400:
            raise RuntimeError(f"ask {status}: {payload}")
        return str(payload.get("reply") or "")

    def chat(self, question: str) -> tuple[str, str]:
        status, started = self._json("POST", "/api/twin/start", {})
        if status >= 400:
            raise RuntimeError(f"twin start {status}: {started}")
        conversation_id = str(started.get("conversation_id") or "")
        request = urllib.request.Request(
            self.base + "/api/twin/message",
            data=json.dumps({"conversation_id": conversation_id, "message": question}).encode("utf-8"),
            method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            body = response.read().decode("utf-8", errors="replace")
        text = ""
        for line in body.splitlines():
            if line.startswith("data: "):
                try:
                    chunk = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict) and chunk.get("text"):
                    text += str(chunk["text"])
        return conversation_id, text

    def transcribe(self, wav: bytes) -> bool:
        boundary = "heirloomselftest"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{LABEL}.wav"\r\n'
            "Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            self.base + "/api/memory-loop/transcribe",
            data=head + wav + tail,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status < 500
        except urllib.error.HTTPError as exc:
            return exc.code != 503


def cleanup(db: Any, user_id: str, card_id: str, prompt_id: str, conversation_ids: list[str], token: str) -> None:
    if card_id:
        db.memory_cards.delete_many({"user_id": user_id, "card_id": card_id})
        db.entries.delete_many({"user_id": user_id, "card_id": card_id})
    db.memory_cards.delete_many({"user_id": user_id, "title": {"$regex": LABEL}})
    db.entries.delete_many({"user_id": user_id, "content": {"$regex": LABEL}})
    if prompt_id:
        db.daily_prompts.delete_many({"user_id": user_id, "prompt_id": prompt_id})
    db.daily_prompts.delete_many({"user_id": user_id, "key": LABEL})
    for conversation_id in conversation_ids:
        db.conversations.delete_many({"user_id": user_id, "conversation_id": conversation_id})
        db.memory_episodes.delete_many({"user_id": user_id, "conversation_id": conversation_id})
    if token:
        db.user_sessions.delete_many({"session_token": token})


def _db() -> Any:
    from pymongo import MongoClient

    url = (os.environ.get("MONGO_URL") or "").strip()
    if not url:
        raise RuntimeError("MONGO_URL is not set")
    name = (os.environ.get("DB_NAME") or "heirloom").strip() or "heirloom"
    return MongoClient(url, serverSelectionTimeoutMS=2000)[name]


def run() -> int:
    from session_renew import issue

    db = _db()
    user = db.users.find_one({"audience": "owner"}, {"_id": 0})
    if not user:
        print("FAIL no owner user on this box")
        return 1
    user_id = str(user["user_id"])
    now = datetime.now(timezone.utc)
    issued = issue(now)
    db.user_sessions.insert_one(issued.document(user_id, now))
    api = Api("http://127.0.0.1:8001", issued.session_token)
    card_id = ""
    prompt_id = ""
    conversations: list[str] = []
    try:
        saved = api.answer(f"{LABEL}. {STORY}", DIRECT)
        card = saved.get("card") or {}
        prompt = saved.get("prompt") or {}
        card_id = str(card.get("card_id") or "")
        prompt_id = str(prompt.get("prompt_id") or card.get("prompt_id") or "")
        api.approve(card_id)
        direct = api.ask(DIRECT)
        paraphrase = api.ask(PARAPHRASE)
        chat_id, chat_direct = api.chat(DIRECT)
        para_id, chat_paraphrase = api.chat(PARAPHRASE)
        unknown_id, unknown = api.chat(UNKNOWN)
        conversations.extend([chat_id, para_id, unknown_id])
        heard = api.transcribe(tone_wav())
        return report(judge(direct, paraphrase, chat_direct, chat_paraphrase, unknown, heard))
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {exc}")
        return 1
    finally:
        cleanup(db, user_id, card_id, prompt_id, conversations, issued.session_token)


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
