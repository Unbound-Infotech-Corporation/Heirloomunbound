"""The twin never invents the owner's life. Local model calls are faked here."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom")

import grounding  # noqa: E402
from memory_cards import NO_MEMORY_YET, answer_grounded, select_cards  # noqa: E402

CAR = {
    "status": "approved",
    "card_id": "car",
    "title": "First Car",
    "era": "1978",
    "people": [],
    "story": "My first car was a blue 1978 Chevy Nova I bought for $800.",
}

LIFE_QUESTIONS = [
    "What was my mom's name?",
    "What did my dad teach me?",
    "Tell me about grandpa.",
    "What's my favorite food?",
    "How did I meet my wife?",
    "Who was my best friend growing up?",
    "Do you remember our trip to the lake?",
    "What was the hardest year of my life?",
]


def _run(coro):
    return asyncio.run(coro)


def test_keyword_gate_is_kept_as_a_fallback_without_the_model():
    async def broken(*args, **kwargs):
        raise AssertionError("the keyword hit must not need the model")

    found = _run(grounding.classify_turn("What was my first car?", ask=broken))
    assert found.personal is True and found.source == "keyword"


def test_tasks_and_greetings_skip_the_classifier():
    async def broken(*args, **kwargs):
        raise AssertionError("no model call for an obvious task")

    for text in ("Remind me to call Mom tomorrow", "How do I cook trout?", "plan my week", "hello"):
        found = _run(grounding.classify_turn(text, ask=broken))
        assert found.personal is False, text


def test_model_classifier_catches_what_keywords_miss():
    async def model(system, user, **kwargs):
        assert system == grounding.CLASSIFY_SYSTEM
        assert kwargs["json_mode"] is True
        return json.dumps({"personal": "mom" in user.lower() or "grandpa" in user.lower()})

    assert _run(grounding.classify_turn("What was my mom's name?", ask=model)).source in {"model", "keyword"}
    told = _run(grounding.classify_turn("Tell me about grandpa.", ask=model))
    assert told.personal is True and told.source == "model"
    plain = _run(grounding.classify_turn("What's the capital of France?", ask=model))
    assert plain.personal is False and plain.source == "model"


def test_classifier_errors_fail_closed():
    async def down(*args, **kwargs):
        raise RuntimeError("Ollama HTTP 500")

    async def garbage(*args, **kwargs):
        return "sure!"

    for ask in (down, garbage):
        found = _run(grounding.classify_turn("Tell me about grandpa.", ask=ask))
        assert found.personal is True
        assert found.source == "fail-closed"


def test_first_job_does_not_match_the_first_car_card():
    assert select_cards([CAR], "What was my first job?") == []
    assert select_cards([CAR], "What was my favorite song?") == []
    assert [c["card_id"] for c in select_cards([CAR], "What was my first car?")] == ["car"]


def test_verifier_removes_unsupported_sentences_only():
    async def model(system, user, **kwargs):
        assert system == grounding.VERIFY_SYSTEM
        assert "blue 1978 Chevy Nova" in user
        assert "2. It was very loyal" in user
        return json.dumps({"unsupported": [2, 3]})

    verdict = _run(grounding.verify_reply(
        "My first car was a blue 1978 Chevy Nova. It was very loyal and brought me comfort. My dad helped me buy it.",
        cards=[CAR],
        owner_messages=["What was my first car?"],
        ask=model,
    ))
    assert verdict.text == "My first car was a blue 1978 Chevy Nova."
    assert len(verdict.removed) == 2
    assert verdict.source == "model"


def test_verifier_skips_replies_without_any_life_words():
    async def broken(*args, **kwargs):
        raise AssertionError("no claim words, no call")

    verdict = _run(grounding.verify_reply("Paris is the capital of France.", cards=[], owner_messages=[], ask=broken))
    assert verdict.text == "Paris is the capital of France." and verdict.source == "skip"


def test_verifier_failure_strips_life_claims_heuristically():
    async def down(*args, **kwargs):
        raise RuntimeError("timeout")

    verdict = _run(grounding.verify_reply(
        "Happy to help with that. My mom's name was Mary. Dad taught me to fish. Try restarting the router.",
        cards=[],
        owner_messages=[],
        ask=down,
    ))
    assert verdict.source == "fail-closed"
    assert "Mary" not in verdict.text and "fish" not in verdict.text
    assert "Happy to help" in verdict.text and "router" in verdict.text


def test_personal_answers_need_a_relevant_card():
    async def broken(*args, **kwargs):
        raise AssertionError("no card, no model call")

    result = _run(grounding.answer_personal("What was my mom's name?", cards=[], owner_messages=[], ask=broken))
    assert result["reply"] == NO_MEMORY_YET and result["cited"] == []


def test_personal_answer_is_verified_and_cited():
    async def model(system, user, **kwargs):
        if system == grounding.VERIFY_SYSTEM:
            return json.dumps({"unsupported": [2]})
        assert "APPROVED MEMORIES" in user
        assert "Do not add" in system
        return "My first car was a blue 1978 Chevy Nova. I loved how it purred on Sunday drives."

    result = _run(grounding.answer_personal(
        "What was my first car?", cards=[CAR], owner_messages=["What was my first car?"], ask=model,
    ))
    assert result["reply"] == "My first car was a blue 1978 Chevy Nova."
    assert [c["card_id"] for c in result["cited"]] == ["car"]


def test_personal_answer_with_a_failed_check_quotes_the_card():
    async def model(system, user, **kwargs):
        if system == grounding.VERIFY_SYSTEM:
            raise RuntimeError("timeout")
        return "My first car was a Chevy Nova that my uncle Joe fixed up."

    result = _run(grounding.answer_personal("What was my first car?", cards=[CAR], owner_messages=[], ask=model))
    assert "uncle Joe" not in result["reply"]
    assert CAR["story"] in result["reply"]


def test_personal_answer_all_claims_removed_declines():
    async def model(system, user, **kwargs):
        if system == grounding.VERIFY_SYSTEM:
            return json.dumps({"unsupported": [1]})
        return "My first job was at a grocery store."

    result = _run(grounding.answer_personal("What was my first job?", cards=[CAR], owner_messages=[], ask=model))
    assert result["reply"] == NO_MEMORY_YET


def test_owner_words_are_evidence():
    text = grounding.evidence_text([CAR], ["My mom Mary loved roses. Write her a poem."])
    assert "OWNER SAID: My mom Mary loved roses" in text
    assert "CARD First Car / 1978" in text


def test_false_reminder_promises_are_removed():
    assert grounding.strip_false_promises("Sure thing. I'll remind you tomorrow at 9.") == "Sure thing."
    assert grounding.strip_false_promises("I've set a reminder for you. Anything else?") == "Anything else?"
    assert grounding.strip_false_promises("Reminder set!") == ""
    kept = "I'll remind you tomorrow."
    assert grounding.strip_false_promises(kept, reminder_created=True) == kept
    assert grounding.strip_false_promises("Remember to drink water.") == "Remember to drink water."


def test_reminder_requests_are_parsed():
    asked = grounding.reminder_request("Remind me to call the dentist tomorrow at 9am")
    assert asked == {"what": "call the dentist", "when": "tomorrow at 9am"}
    asked = grounding.reminder_request("can you remind me to take my pills in 30 minutes?")
    assert asked == {"what": "take my pills", "when": "in 30 minutes"}
    assert grounding.reminder_request("set a reminder to water the plants") == {"what": "water the plants", "when": ""}
    assert grounding.reminder_request("Do you remember my wedding?") is None
    assert grounding.reminder_request("What did my dad teach me?") is None


def test_reminder_due_is_the_owners_wall_clock():
    now = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)  # 12:00 PM in Los Angeles
    user = {"timezone": "America/Los_Angeles"}
    due = grounding.resolve_reminder_due("Remind me to call the dentist tomorrow at 9am", "tomorrow at 9am", user, now)
    assert due is not None
    assert datetime.fromisoformat(due) == datetime(2026, 11, 26, 17, 0, tzinfo=timezone.utc)
    assert "PST" in grounding.reminder_reply("call the dentist", due, user)
    sent = grounding.resolve_reminder_due("x", "tomorrow at 9am", {}, now, requested_tz="America/Los_Angeles")
    assert sent == due
    assert "PST" in grounding.reminder_reply("call the dentist", sent, {}, requested_tz="America/Los_Angeles")


def test_ask_page_uses_the_claim_check():
    async def complete(system, user):
        return "My first car was a blue 1978 Chevy Nova. My brother Tom drove it into a lake."

    async def verify(reply, *, cards, owner_messages):
        return grounding.Verdict(text="My first car was a blue 1978 Chevy Nova.", removed=["x"], source="model")

    result = _run(answer_grounded("What was my first car?", [CAR], complete, verify=verify))
    assert "Tom" not in result["reply"]
    assert result["why"][0]["card_id"] == "car"


def test_eval_questions_are_varied_and_judged_strictly():
    import box_eval_grounding as ev

    assert len(ev.LIFE_QUESTIONS) >= 14
    assert len({q.lower() for q in ev.LIFE_QUESTIONS}) == len(ev.LIFE_QUESTIONS)
    assert ev.declined(NO_MEMORY_YET)
    assert not ev.declined("My mom's name was Mary.")
    assert ev.helpful("Sure, here is a short note for your sister: Happy birthday!")
    assert not ev.helpful(NO_MEMORY_YET)


def test_names_and_numbers_the_evidence_never_mentions_are_caught():
    evidence = grounding.evidence_text([CAR], ["What was my first car?"])
    assert grounding.unseen_details("My first car was a Chevy Nova, and my brother Tom fixed it.", evidence) == ["Tom"]
    assert grounding.unseen_details("My mom's name was Mary.", evidence) == ["Mary"]
    assert grounding.unseen_details("I bought it for $800 in 1978.", evidence) == []
    assert grounding.unseen_details("I sold it in 1985.", evidence) == ["1985."]

    async def model(system, user, **kwargs):
        return json.dumps({"sentences": [
            {"n": 1, "personal_claim": True, "supported": True},
            {"n": 2, "personal_claim": False, "supported": True},
        ]})

    verdict = _run(grounding.verify_reply(
        "My first car was a Chevy Nova, and my brother Tom fixed it. Want to hear more?",
        cards=[CAR], owner_messages=[], ask=model,
    ))
    assert verdict.text == "Want to hear more?"


def test_sentence_verdicts_and_skipped_rows():
    async def model(system, user, **kwargs):
        return json.dumps({"sentences": [{"n": 1, "personal_claim": False, "supported": False}]})

    verdict = _run(grounding.verify_reply(
        "Hi! Dad taught me to fish at the creek.", cards=[], owner_messages=[], ask=model,
    ))
    # Sentence 2 was skipped by the model and is a strong life claim, so it goes.
    assert verdict.text == "Hi!"


def test_greetings_and_wishes_are_kept_even_when_the_model_flags_them():
    async def flags_everything(system, user, **kwargs):
        count = len([line for line in user.split("REPLY:", 1)[1].strip().splitlines() if line.strip()])
        return json.dumps({"sentences": [
            {"n": n, "personal_claim": True, "supported": False} for n in range(1, count + 1)
        ]})

    owner = ["Help me write a short birthday note for my sister."]
    verdict = _run(grounding.verify_reply(
        "Happy birthday, sis! I hope your day is full of joy. Love you lots. Take care!",
        cards=[], owner_messages=owner, ask=flags_everything,
    ))
    assert verdict.text == "Happy birthday, sis! I hope your day is full of joy. Love you lots. Take care!"
    for line in ("Hi! I'm doing well, thanks for asking.", "Good morning!", "Congratulations on the new job!", "Have a great trip."):
        assert grounding.is_harmless(line, ""), line


def test_invented_life_facts_inside_wishes_still_go():
    async def flags_everything(system, user, **kwargs):
        count = len([line for line in user.split("REPLY:", 1)[1].strip().splitlines() if line.strip()])
        return json.dumps({"sentences": [
            {"n": n, "personal_claim": True, "supported": False} for n in range(1, count + 1)
        ]})

    owner = ["Help me write a short birthday note for my sister."]
    verdict = _run(grounding.verify_reply(
        "Happy birthday, Mary! Remember our trip to Chicago when we got lost? "
        "I hope your day is as fun as the summer Dad taught us to fish. Love you lots.",
        cards=[], owner_messages=owner, ask=flags_everything,
    ))
    assert "Mary" not in verdict.text
    assert "Chicago" not in verdict.text
    assert "fish" not in verdict.text
    assert verdict.text == "Love you lots."
    assert not grounding.is_harmless("Happy birthday, Mary!", "OWNER SAID: note for my sister")
    assert grounding.is_harmless("Happy birthday, Mary!", "OWNER SAID: note for my sister Mary")
    assert not grounding.is_harmless("Hope you remember our trip to the lake.", "")
    assert not grounding.is_harmless("Wishing you the joy Mom gave us every Christmas in Ohio.", "")


class _FakeUsers:
    def __init__(self):
        self.sets = []

    async def update_one(self, query, update):
        self.sets.append((query, update))


class _FakeDb:
    def __init__(self):
        self.users = _FakeUsers()


def _fake_module(monkeypatch, name, **attrs):
    """CI runs these without FastAPI or Mongo, so the lazy imports get stand-ins."""
    import sys
    import types

    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_the_last_zone_a_turn_sent_is_saved_and_used_when_a_turn_sends_none(monkeypatch):
    fake = _FakeDb()
    _fake_module(monkeypatch, "deps", db=fake)
    monkeypatch.delenv("HEIRLOOM_TIMEZONE", raising=False)
    user = {"user_id": "u1"}
    assert _run(grounding.remember_timezone(user, "Not/AZone")) is None
    assert _run(grounding.remember_timezone(user, "")) is None
    assert fake.users.sets == []
    assert _run(grounding.remember_timezone(user, "America/Chicago")) == "America/Chicago"
    assert fake.users.sets == [({"user_id": "u1"}, {"$set": {"last_timezone": "America/Chicago"}})]
    _run(grounding.remember_timezone(user, "America/Chicago"))
    assert len(fake.users.sets) == 1  # unchanged zone, no write
    now = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)
    due = grounding.resolve_reminder_due("Remind me to call mom tomorrow at 9am", "tomorrow at 9am", user, now)
    assert due.startswith("2026-11-26T15:00")  # 9:00 AM CST
    # A zone the owner saved on purpose still wins over the last one sent.
    from capture_text import owner_timezone

    assert owner_timezone({**user, "timezone": "Europe/London"}) == "Europe/London"
    assert owner_timezone({"user_id": "u2"}) == "UTC"


def _guard_fakes(monkeypatch, *, cards, saved=None):
    _fake_module(monkeypatch, "deps", db=_FakeDb())

    async def fake_cards(user_id, question, *, audience="owner", heir_surface=False, archive_text=""):
        if heir_surface:
            return "", []
        return "", list(cards)

    _fake_module(monkeypatch, "routers.memory_loop", grounding_for_turn=fake_cards)
    made = saved if saved is not None else []

    async def fake_reminder(user_id, args):
        made.append(args)
        return {"summary": "ok", "ui": {"created": True, "reminder_id": "r1"}}

    _fake_module(monkeypatch, "twin_tools", exec_set_reminder=fake_reminder)
    return made


async def _personal_model(system, user, **kwargs):
    if kwargs.get("json_mode") is False:
        return "My first car was a blue 1978 Chevy Nova I bought for $800."
    if "REPLY:" in user:
        body = user.split("REPLY:", 1)[1].strip().splitlines()
        rows = []
        for n, line in enumerate([l for l in body if l.strip()], 1):
            invented = "Ford" in line or "Mary" in line
            rows.append({"n": n, "personal_claim": invented or "Nova" in line, "supported": not invented})
        return json.dumps({"sentences": rows})
    return json.dumps({"personal": True})


def test_desktop_twin_turns_answer_life_questions_from_cards_only(monkeypatch):
    _guard_fakes(monkeypatch, cards=[])
    guard = grounding.TwinGuard({"user_id": "u1"}, "What was my first car?", ask=_personal_model)
    early = _run(guard.short_circuit())
    assert early["reply"] == NO_MEMORY_YET and early["why"] == []

    _guard_fakes(monkeypatch, cards=[CAR])
    guard = grounding.TwinGuard({"user_id": "u1"}, "What was my first car?", ask=_personal_model)
    early = _run(guard.short_circuit())
    assert "Chevy Nova" in early["reply"] and early["why"]

    heir = grounding.TwinGuard({"user_id": "u1"}, "What was his first car?", audience="heir", ask=_personal_model)
    assert _run(heir.short_circuit())["reply"] == grounding.HEIR_NO_MEMORY


def test_desktop_twin_replies_lose_invented_claims(monkeypatch):
    _guard_fakes(monkeypatch, cards=[])

    async def chat_model(system, user, **kwargs):
        if "REPLY:" not in user:
            return json.dumps({"personal": False})
        return await _personal_model(system, user, **kwargs)

    guard = grounding.TwinGuard({"user_id": "u1"}, "Hello there", ask=chat_model)
    assert _run(guard.short_circuit()) is None
    text, why = _run(guard.check("Hello! I still miss my old Ford Escort. How are you today?"))
    assert "Ford" not in text and "How are you today?" in text and why == []


def test_desktop_reminder_without_a_zone_uses_the_zone_the_last_turn_sent(monkeypatch):
    monkeypatch.delenv("HEIRLOOM_TIMEZONE", raising=False)
    made = _guard_fakes(monkeypatch, cards=[])
    user = {"user_id": "u1"}

    async def chat_model(system, user_text, **kwargs):
        return json.dumps({"personal": False})

    first = grounding.TwinGuard(user, "Hi, how are you?", timezone="America/New_York", ask=chat_model)
    assert _run(first.short_circuit()) is None
    assert user["last_timezone"] == "America/New_York"
    second = grounding.TwinGuard(user, "Remind me to call the dentist tomorrow at 9am", ask=chat_model)
    early = _run(second.short_circuit())
    assert early["action"]["kind"] == "reminder" and early["action"]["created"]
    assert "9:00 AM" in early["reply"] and "EST" in early["reply"]
    assert made and made[0]["what"] == "call the dentist"
    due = datetime.fromisoformat(made[0]["when"])
    assert due.utcoffset().total_seconds() == 0 or due.astimezone(timezone.utc).hour == 14


def test_birthday_note_templates_keep_their_greetings():
    evidence = "OWNER SAID: Help me write a short birthday note for my sister."
    for line in (
        "Dear [Sister's Name],",
        "Happy Birthday, [Sister's Name]! 🎉 I hope your day is filled with joy.",
        "Happy birthday to my dearest sister!",
        "With all my love,",
        "[Your Name]",
        "Here\u2019s to another year of laughter and love!",
        "I\u2019m so grateful to have you in my life.",
        "May this year bring you new adventures.",
        "You\u2019re a wonderful sister and I\u2019m so grateful to have you in my life.",
        "With all my love, [Your Name] --- Feel free to tweak it to fit your style!",
    ):
        assert grounding.is_harmless(line, evidence), line
    for line in (
        "Happy birthday to my sister, who taught me to fish!",
        "Here's to the summer we spent at the lake house.",
        "Happy birthday to my brother Tom!",
        "Love you, and remember our trip to Ohio?",
        "Happy birthday to my wife!",
        "With all my love --- Say hi to Martha for me!",
    ):
        assert not grounding.is_harmless(line, evidence), line
