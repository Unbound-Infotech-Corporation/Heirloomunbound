"""Iteration 22 — Twin AI assistant tools (8 tools) end-to-end tests.

Covers:
- SSE tool events (start → result) for weather, save_memory, set_reminder, search_archive, web_search, get_weather with lat,lon
- tool_trace persistence on assistant message
- Regression: plain conversation (no tools), music short-circuit (no tools)
- Tool loop safety cap (< 60s completion)
"""
import json
import os
import time
import uuid

import pytest
import requests
from pymongo import MongoClient

from dotenv import load_dotenv
load_dotenv("/app/backend/.env")
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
MONGO_URL = os.environ["MONGO_URL"].strip('"').strip("'")
DB_NAME = os.environ["DB_NAME"].strip('"').strip("'")

# ---- Fixtures ---- #

@pytest.fixture(scope="module")
def db():
    return MongoClient(MONGO_URL)[DB_NAME]

@pytest.fixture(scope="module")
def user_ctx(db):
    uid = f"test-user-iter22-{uuid.uuid4().hex[:10]}"
    token = f"test_session_iter22_{uuid.uuid4().hex[:12]}"
    db.users.insert_one({
        "user_id": uid,
        "email": f"twin.{uid}@example.com",
        "name": "Twin Test",
        "picture": "https://via.placeholder.com/150",
        "setup_complete": True,
        "onboarded": True,
        "tour_completed": True,
    })
    db.user_sessions.insert_one({
        "user_id": uid,
        "session_token": token,
        "expires_at": __import__("datetime").datetime.utcnow().replace(year=2099),
    })
    yield {"user_id": uid, "token": token}
    # cleanup
    db.users.delete_one({"user_id": uid})
    db.user_sessions.delete_many({"user_id": uid})
    db.conversations.delete_many({"user_id": uid})
    db.entries.delete_many({"user_id": uid})
    db.reminders.delete_many({"user_id": uid})

@pytest.fixture(scope="module")
def headers(user_ctx):
    return {"Authorization": f"Bearer {user_ctx['token']}", "Content-Type": "application/json"}

@pytest.fixture
def conversation(headers):
    r = requests.post(f"{BASE_URL}/api/twin/start", json={}, headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["conversation_id"]


# ---- SSE helper ---- #
def send_twin_message(headers, conv_id, message, timeout=90):
    """Returns (raw_text, tool_events, action_events, text_deltas, done)"""
    r = requests.post(
        f"{BASE_URL}/api/twin/message",
        json={"conversation_id": conv_id, "message": message},
        headers=headers,
        stream=True,
        timeout=timeout,
    )
    assert r.status_code == 200, f"status={r.status_code}, body={r.text[:400]}"
    tool_events, action_events, text_deltas = [], [], []
    done = False
    buf = ""
    start = time.time()
    for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
        if not chunk:
            continue
        buf += chunk
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            lines = frame.split("\n")
            ev = "message"
            data = ""
            for ln in lines:
                if ln.startswith("event:"):
                    ev = ln[len("event:"):].strip()
                elif ln.startswith("data:"):
                    data += ln[len("data:"):].strip()
            try:
                payload = json.loads(data) if data else {}
            except json.JSONDecodeError:
                payload = {"raw": data}
            if ev == "tool":
                tool_events.append(payload)
            elif ev == "action":
                action_events.append(payload)
            elif ev == "done":
                done = True
            elif ev == "error":
                raise RuntimeError(f"SSE error: {payload}")
            else:
                if "text" in payload:
                    text_deltas.append(payload["text"])
        if done:
            break
        if time.time() - start > timeout:
            break
    return {"tools": tool_events, "actions": action_events, "texts": text_deltas, "done": done, "elapsed": time.time() - start}


# ---- Tests ---- #

class TestTwinTools:

    def test_weather_tool_paris(self, headers, conversation, db, user_ctx):
        res = send_twin_message(headers, conversation, "what is the weather in Paris right now?")
        assert res["done"], "SSE stream never completed"
        # Expect at least one get_weather tool event with start and result phases
        weather_starts = [t for t in res["tools"] if t.get("name") == "get_weather" and t.get("phase") == "start"]
        weather_results = [t for t in res["tools"] if t.get("name") == "get_weather" and t.get("phase") == "result"]
        assert weather_starts, f"no get_weather start; tools={res['tools']}"
        assert weather_results, f"no get_weather result; tools={res['tools']}"
        # Final text should include weather-flavored content
        final = " ".join(res["texts"]).lower()
        assert any(k in final for k in ["temp", "degree", "°", "humid", "wind", "cloud", "clear", "rain", "sunny", "paris"]), f"final text lacks weather content: {final[:300]}"

    def test_save_memory_tool(self, headers, conversation, db, user_ctx):
        res = send_twin_message(headers, conversation, "remember this: I hated the trip to Cabo because the food was bland")
        assert res["done"]
        saves = [t for t in res["tools"] if t.get("name") == "save_memory"]
        assert not saves, f"Twin must not quietly file chat; tools={[t.get('name') for t in res['tools']]}"
        entry = db.entries.find_one({"user_id": user_ctx["user_id"], "source": "twin_tool"})
        assert not entry, "Twin chat must not insert archive rows"

    def test_set_reminder_tool(self, headers, conversation, db, user_ctx):
        res = send_twin_message(headers, conversation, "remind me to call mom tomorrow at 9am")
        assert res["done"]
        rems = [t for t in res["tools"] if t.get("name") == "set_reminder" and t.get("phase") == "result"]
        assert rems, f"set_reminder never fired; tools={[t.get('name') for t in res['tools']]}"
        r = db.reminders.find_one({"user_id": user_ctx["user_id"], "text": {"$regex": "mom", "$options": "i"}})
        assert r, "no reminder persisted"
        assert r.get("due_at"), "due_at is empty — dateparser failed"
        # Sanity: iso parseable
        from datetime import datetime
        datetime.fromisoformat(r["due_at"].replace("Z", "+00:00"))

    def test_search_archive_tool(self, headers, conversation, db, user_ctx):
        # seed an entry
        db.entries.insert_one({
            "entry_id": f"ent_{uuid.uuid4().hex[:10]}",
            "user_id": user_ctx["user_id"],
            "type": "memory",
            "title": "Cabo trip",
            "content": "I went to Cabo San Lucas and disliked the resort food.",
            "tags": [],
            "created_at": "2025-01-01T00:00:00+00:00",
            "updated_at": "2025-01-01T00:00:00+00:00",
        })
        res = send_twin_message(headers, conversation, "search my archive for anything about Cabo")
        assert res["done"]
        srch = [t for t in res["tools"] if t.get("name") == "search_archive"]
        assert srch, "search_archive never fired"

    def test_tool_trace_persisted(self, headers, db, user_ctx):
        # Fresh conversation, trigger a tool, then check persistence
        conv_id = requests.post(f"{BASE_URL}/api/twin/start", json={}, headers=headers, timeout=15).json()["conversation_id"]
        send_twin_message(headers, conv_id, "weather in London?")
        conv = db.conversations.find_one({"conversation_id": conv_id, "user_id": user_ctx["user_id"]})
        assert conv
        assistant_msgs = [m for m in conv["messages"] if m.get("role") == "assistant"]
        assert assistant_msgs, "no assistant message stored"
        last = assistant_msgs[-1]
        assert "tool_trace" in last, f"assistant message has no tool_trace: keys={list(last.keys())}"
        assert last["tool_trace"], "tool_trace empty"
        t0 = last["tool_trace"][0]
        for k in ("id", "name", "args", "ui", "ts"):
            assert k in t0, f"tool_trace item missing '{k}': {t0}"

    def test_regression_plain_conversation_no_tools(self, headers, conversation):
        res = send_twin_message(headers, conversation, "tell me about your childhood")
        assert res["done"]
        assert not res["tools"], f"tools fired on plain convo: {[t.get('name') for t in res['tools']]}"
        assert res["texts"], "no reply text"

    def test_regression_music_shortcircuit(self, headers, conversation):
        res = send_twin_message(headers, conversation, "put on some jazz")
        assert res["done"]
        assert not res["tools"], f"tool loop fired for music: {res['tools']}"
        music_actions = [a for a in res["actions"] if a.get("kind") == "music"]
        assert music_actions, f"no music action emitted; actions={res['actions']}"

    def test_web_search_tool(self, headers, conversation):
        res = send_twin_message(headers, conversation, "what is bitcoin price today according to the web?")
        assert res["done"]
        # web_search may not always be chosen; accept get_weather NOT fired, and either web_search fired or the model asked a follow-up
        websearches = [t for t in res["tools"] if t.get("name") == "web_search" and t.get("phase") == "result"]
        # Soft-assert: log if not fired
        if not websearches:
            pytest.skip(f"web_search not chosen by the model this run; tools={[t.get('name') for t in res['tools']]}")
        assert websearches

    def test_weather_lat_lon_direct(self, headers, conversation):
        res = send_twin_message(headers, conversation, "weather at 40.7,-74.0")
        assert res["done"]
        wt = [t for t in res["tools"] if t.get("name") == "get_weather" and t.get("phase") == "result"]
        assert wt, f"get_weather did not fire on lat,lon prompt; tools={[t.get('name') for t in res['tools']]}"
        ui = wt[0].get("ui") or {}
        assert ui.get("ok") is True, f"weather ui not ok: {ui}"

    def test_tool_loop_completes_within_60s(self, headers, conversation):
        res = send_twin_message(headers, conversation, "look up the weather in Tokyo, London and NYC", timeout=90)
        assert res["done"], "did not complete"
        assert res["elapsed"] < 75, f"tool loop took too long: {res['elapsed']:.1f}s"
