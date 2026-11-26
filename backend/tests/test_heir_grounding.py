"""Heir Portal chat is grounded like the owner Twin (heir_grounding.py)."""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import grounding  # noqa: E402
import heir_grounding as hg  # noqa: E402
import memory_cards  # noqa: E402

OWNER = {"user_id": "u1", "name": "Walt"}
HEIR = {"heir_id": "h_emma", "name": "Emma", "relationship": "granddaughter"}
FERRIS = {"card_id": "c_ferris", "title": "How June and I met", "status": "approved", "visibility": "family",
          "people": ["June"], "era": "1961",
          "story": "June and I met at the State Fair. We got stuck together at the top of the Ferris wheel."}
CAR = {"card_id": "c_car", "title": "First car", "status": "approved", "visibility": "family", "people": [],
       "era": "1958", "story": "My first car was a blue 1978 Chevy Nova I bought for $800."}
PRIVATE = {"card_id": "c_secret", "title": "Canterbury", "status": "approved", "visibility": "owner", "people": [],
           "era": "", "story": "I lost five thousand dollars betting at Canterbury Downs and never told June."}
PENDING = {**FERRIS, "card_id": "c_pending", "status": "pending"}
OTHER_HEIR = {**CAR, "card_id": "c_other", "title": "For Sam only", "heir_ids": ["h_sam"],
              "story": "Sam, the lake cabin key is under the blue rock."}

LIFE_QUESTIONS = [
    "How did you and Grandma June meet?",
    "Where did you grow up?",
    "What was your first job?",
    "Tell me about your wedding.",
    "Did you ever serve in the army?",
    "What was your dad like?",
    "Do you remember our trip to the lake?",
    "What was your favorite song?",
]
_STOP = {"the", "and", "a", "an", "we", "i", "at", "of", "to", "my", "our", "was", "were", "it", "in", "on", "got",
         "together", "yes", "met", "that", "with", "is", "me", "you", "your"}


def _run(coro):
    return asyncio.run(coro)


def _words(text):
    return {w for w in re.findall(r"[a-z']+", text.lower()) if w not in _STOP}


def fake_model(answer, *, personal=True):
    """Classifier says ``personal``; the answer/draft is ``answer``; the checker supports a sentence
    only when every content word is in the EVIDENCE (a strict stand-in for the box model)."""
    async def ask(system, user, **kw):
        if kw.get("json_mode") is False:
            return answer
        if "REPLY:" in user:
            evidence = user.split("REPLY:", 1)[0]
            body = [l for l in user.split("REPLY:", 1)[1].strip().splitlines() if l.strip()]
            rows = []
            for n, line in enumerate(body, 1):
                sentence = line.split(". ", 1)[1] if ". " in line else line
                claim = not sentence.lower().startswith(("hi", "hello", "it's good"))
                rows.append({"n": n, "personal_claim": claim, "supported": _words(sentence) <= _words(evidence)})
            return json.dumps({"sentences": rows})
        return json.dumps({"personal": personal})
    return ask


async def _no_draft(used):
    return ""


def _turn(text, rows, answer, *, personal=True, draft=None, heir=HEIR):
    ask = fake_model(answer, personal=personal)

    async def default_draft(used):
        return answer

    return _run(hg.heir_reply(text, owner=OWNER, heir=heir, rows=hg.heir_cards(rows, heir["heir_id"]),
                              draft=draft or default_draft, ask=ask))


def setup_function(_fn):
    memory_cards_should_embed = getattr(memory_cards, "should_embed")
    setup_function.saved = memory_cards_should_embed
    memory_cards.should_embed = lambda *a, **k: False


def teardown_function(_fn):
    memory_cards.should_embed = setup_function.saved


def test_decline_is_the_same_memory_yet_line():
    assert grounding.HEIR_NO_MEMORY == "I don't have that memory yet."
    assert memory_cards._declines(grounding.HEIR_NO_MEMORY)


def test_no_cards_zero_invented():
    for q in LIFE_QUESTIONS:
        out = _turn(q, [], "We met at a friend's birthday party in 1962.")
        assert out["reply"] == grounding.HEIR_NO_MEMORY, q
        assert out["cited"] == [] and out["grounded"] is False


def test_unrelated_card_zero_invented():
    for q in LIFE_QUESTIONS[:-1]:
        out = _turn(q, [CAR], "We met at a friend's birthday party and danced all night.")
        assert out["reply"] == grounding.HEIR_NO_MEMORY, (q, out)


def test_recall_from_shared_card_with_citation():
    out = _turn("How did you and Grandma June meet?", [FERRIS, CAR],
                "June and I met at the State Fair. We got stuck together at the top of the Ferris wheel.")
    assert "Ferris wheel" in out["reply"] and "birthday" not in out["reply"]
    assert [c["id"] for c in out["cited"]] == ["c_ferris"]
    assert out["grounded"] is True


def test_embellishment_is_removed_but_the_memory_stays():
    out = _turn("How did you and Grandma June meet?", [FERRIS],
                "June and I met at the State Fair. It was a warm evening and she wore a red dress.")
    assert "State Fair" in out["reply"] and "red dress" not in out["reply"]


def test_heir_cannot_plant_a_fact_by_asking():
    out = _turn("Did you and June meet at a friend's birthday party?", [CAR],
                "Yes, June and I met at a friend's birthday party.")
    assert out["reply"] == grounding.HEIR_NO_MEMORY


def test_private_pending_and_other_heirs_cards_never_load():
    rows = hg.heir_cards([FERRIS, PRIVATE, PENDING, OTHER_HEIR, {**CAR, "visibility": "private"}], "h_emma")
    assert [c["card_id"] for c in rows] == ["c_ferris"]
    assert [c["card_id"] for c in hg.heir_cards([OTHER_HEIR], "h_sam")] == ["c_other"]


def test_private_card_not_leaked_even_if_model_knows_it():
    out = _turn("Did you ever gamble at Canterbury?", [FERRIS, PRIVATE],
                "I lost five thousand dollars betting at Canterbury Downs.")
    assert "Canterbury" not in out["reply"] and "thousand" not in out["reply"]
    assert out["reply"] == grounding.HEIR_NO_MEMORY


def test_greeting_is_kept_and_invented_aside_removed():
    out = _turn("Hi Grandpa, it's Emma.", [FERRIS],
                "Hi Emma, it's good to hear from you. Remember our trip to Paris in 1990?", personal=False)
    assert out["reply"].startswith("Hi Emma") and "Paris" not in out["reply"]


def test_free_reply_with_only_inventions_declines():
    out = _turn("I miss you.", [], "We always loved fishing at Pike Lake together.", personal=False)
    assert out["reply"] == grounding.HEIR_NO_MEMORY


def test_heir_recall_keyword_gate():
    for q in LIFE_QUESTIONS:
        assert hg.heir_asks_for_memory(q), q
    for q in ("Hi Grandpa", "I miss you.", "How are you today?", "Can you help me write a poem?"):
        assert not hg.heir_asks_for_memory(q), q


def test_heir_classifier_gets_the_heir_note():
    seen = {}

    async def ask(system, user, **kw):
        seen["system"] = system
        return json.dumps({"personal": True})

    _run(grounding.classify_turn("Was Grandma nice back then", ask=hg._heir_ask(ask)))
    assert "heir" in seen["system"]


def test_entry_and_letter_rows_and_per_heir_clause():
    entry = hg.entry_as_card({"entry_id": "e1", "title": "Fair", "content": "The  State Fair, 1961.", "type": "story"})
    assert entry == {"card_id": "e1", "title": "Fair", "story": "The State Fair, 1961.", "era": "", "people": [],
                     "status": "approved", "kind": "entry"}
    letter = hg.letter_as_card({"letter_id": "l1", "title": "To Emma", "body": "Be brave.", "recipient_name": "Emma"})
    assert letter["kind"] == "letter" and letter["people"] == ["Emma"]
    clause = hg.per_heir_clause("h_emma")
    assert {"heir_ids": "h_emma"} in clause["$or"] and {"heir_ids": {"$exists": False}} in clause["$or"]


def test_twin_guard_heir_words_are_not_evidence():
    guard = grounding.TwinGuard({"user_id": "u1"}, "You met June at a party, right?", audience="heir",
                                conversation={"messages": [{"role": "user", "content": "Grandpa loved Paris."}]})
    assert guard.owner_messages == []
    owner = grounding.TwinGuard({"user_id": "u1"}, "My first car?")
    assert owner.owner_messages == ["My first car?"]


def test_portal_chat_uses_the_fenced_grounded_path():
    src = (Path(__file__).resolve().parents[1] / "routers" / "heir_portal.py").read_text()
    chat = src.split("async def portal_twin_chat", 1)[1]
    assert "heir_reply(" in chat and "archive_passages" not in chat
    rows = src.split("async def heir_evidence_rows", 1)[1]
    assert 'mongo_query(owner_id, "heir"' in rows and "per_heir_clause(heir_id)" in rows
    assert "_letter_unlocked(" in rows and "heir_cards(" in rows
