"""Phase 3 bug-fix tests: SSE JSON framing + multi-turn memory for interviewer & twin."""
import json
import os
import time
import httpx
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or \
           "https://voice-clone-hub-20.preview.emergentagent.com"
API = f"{BASE_URL}/api"

TOKEN = "p3_sess_1782370692411"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _consume_sse(url: str, payload: dict, timeout: float = 90.0):
    """Stream SSE; return (full_text, raw_events, done_seen, error_payload)."""
    full = ""
    raw_events = []
    done_seen = False
    error_payload = None
    with httpx.stream("POST", url, headers=HEADERS, json=payload, timeout=timeout) as r:
        if r.status_code != 200:
            return full, raw_events, done_seen, {"http_status": r.status_code, "body": r.read().decode()}
        buf = ""
        for chunk in r.iter_text():
            buf += chunk
            while "\n\n" in buf:
                evt, buf = buf.split("\n\n", 1)
                raw_events.append(evt)
                lines = evt.split("\n")
                event_name = ""
                data_lines = []
                for line in lines:
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip(" "))
                data_str = "\n".join(data_lines)
                if event_name == "done":
                    done_seen = True
                elif event_name == "error":
                    try:
                        error_payload = json.loads(data_str)
                    except Exception:
                        error_payload = {"raw": data_str}
                elif data_str:
                    # default event = text delta — MUST be JSON {"text": "..."}
                    parsed = json.loads(data_str)
                    assert isinstance(parsed, dict), f"data not JSON dict: {data_str!r}"
                    assert "text" in parsed, f"data missing .text: {data_str!r}"
                    full += parsed["text"]
    return full, raw_events, done_seen, error_payload


# ---------------- BUG #2 — SSE framing ----------------
class TestSSEFraming:
    def test_interviewer_sse_json_framing_multi_paragraph(self):
        # Start fresh convo
        r = requests.post(f"{API}/interviewer/start", headers=HEADERS, json={})
        assert r.status_code == 200, r.text
        cid = r.json()["conversation_id"]

        # Ask for multi-paragraph reply with blank lines (real \n in output)
        prompt = ("Please write me three short paragraphs about three different childhood memories, "
                  "each separated by a blank line.")
        full, raw, done, err = _consume_sse(
            f"{API}/interviewer/message",
            {"conversation_id": cid, "message": prompt},
        )
        assert err is None, f"unexpected error event: {err}"
        assert done, "no event: done arrived"
        assert len(full) > 50, f"reply too short: {full!r}"
        # newlines should survive intact (multi-paragraph response)
        assert "\n" in full, f"expected newlines in concatenated text, got: {full!r}"

    def test_interviewer_sse_error_event_on_bad_conv(self):
        # Use clearly invalid conversation_id -> backend raises 404 BEFORE stream starts.
        r = requests.post(
            f"{API}/interviewer/message",
            headers=HEADERS,
            json={"conversation_id": "conv_does_not_exist_zzz", "message": "hello"},
        )
        # Backend raises HTTPException before the StreamingResponse — 404 is correct.
        assert r.status_code == 404, r.text


# ---------------- BUG #1 — multi-turn memory ----------------
class TestInterviewerMemory:
    def test_remembers_city_across_turns(self):
        r = requests.post(f"{API}/interviewer/start", headers=HEADERS, json={})
        assert r.status_code == 200
        cid = r.json()["conversation_id"]

        # Turn 1: give a fact
        full1, _, done1, err1 = _consume_sse(
            f"{API}/interviewer/message",
            {"conversation_id": cid, "message": "My name is Marcus and I grew up in Tulsa."},
        )
        assert err1 is None and done1, f"turn1 err={err1} done={done1}"
        assert len(full1) > 5

        # small pause to let DB write commit
        time.sleep(0.5)

        # Turn 2: ask what city
        full2, _, done2, err2 = _consume_sse(
            f"{API}/interviewer/message",
            {"conversation_id": cid, "message": "What city did I just say I grew up in?"},
        )
        assert err2 is None and done2
        assert "tulsa" in full2.lower(), f"twin lost memory of Tulsa; reply was: {full2!r}"


class TestTwinMemory:
    def test_remembers_number_across_turns(self):
        r = requests.post(f"{API}/twin/start", headers=HEADERS, json={})
        assert r.status_code == 200
        cid = r.json()["conversation_id"]

        full1, _, done1, err1 = _consume_sse(
            f"{API}/twin/message",
            {"conversation_id": cid, "message": "Remember the number 7421."},
        )
        assert err1 is None and done1, f"turn1 err={err1}"
        assert len(full1) > 1

        time.sleep(0.5)

        full2, _, done2, err2 = _consume_sse(
            f"{API}/twin/message",
            {"conversation_id": cid, "message": "What number did I just give you?"},
        )
        assert err2 is None and done2
        assert "7421" in full2, f"twin forgot 7421; reply was: {full2!r}"
