"""Inbound Twin answering turns. No Retell, no Mongo."""
from __future__ import annotations

from phone_inbound import (
    ANGRY_CALM,
    GOODBYE_FAMILY,
    LISTENING,
    MAX_SILENCE_REMINDERS,
    MESSAGE_GOT,
    MESSAGE_KEEP,
    MESSAGE_THANKS,
    SILENCE_BYE,
    SILENCE_STILL,
    UNCLEAR_OFFER,
    UNCLEAR_SPOKEN,
    InboundSession,
    apply_policy_phase,
    caller_display,
    greeting,
    notify_copy,
    phone_system_addendum,
    plan_turn,
    sounds_angry,
    sounds_unclear,
    wants_goodbye,
    wants_message,
)
from phone_policy import (
    DECLINE_SPOKEN,
    HANDOFF_CLOSED,
    HANDOFF_SPOKEN,
    MESSAGE_PROMPT,
    clamp_settings,
    decide_inbound,
    default_settings,
    wants_handoff,
)


def _family(**kwargs):
    base = default_settings()
    base["answering"] = True
    base["allowlist"] = [{"e164": "+15551230000", "name": "Sam", "heir_id": "heir_1"}]
    base["owner_e164"] = "+15559990000"
    base.update(kwargs)
    return clamp_settings(base)


def _session(decision, **kwargs):
    session = InboundSession()
    apply_policy_phase(session, decision)
    for key, value in kwargs.items():
        setattr(session, key, value)
    return session


def test_family_greeting_uses_their_name():
    decision = decide_inbound("+15551230000", _family())
    line = greeting("Alex", decision)
    assert line == "Hey Sam. It's Alex."
    assert "Twin" not in line
    assert "AI" not in line


def test_owner_greeting_is_first_person():
    decision = decide_inbound("+15559990000", _family())
    assert greeting("Alex", decision) == "Hey. It's me."


def test_unknown_anyone_discloses():
    decision = decide_inbound("+15550001111", _family(who_can_call="anyone"))
    line = greeting("Alex", decision)
    assert "Hey, it's Alex." in line
    assert "Heirloom Twin" in line


def test_greeting_once_then_silence_is_not_a_repeat():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision)
    first = plan_turn(
        interaction="response_required",
        user_text="",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert first.speak == "Hey Sam. It's Alex."
    assert session.greeted is True
    second = plan_turn(
        interaction="reminder_required",
        user_text="",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert second.speak == SILENCE_STILL
    assert "Hey Sam" not in second.speak


def test_empty_response_after_greeting_asks_to_repeat():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    out = plan_turn(
        interaction="response_required",
        user_text="",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert out.speak == UNCLEAR_SPOKEN
    assert out.need_twin is False


def test_long_silence_hangs_up():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    last = None
    for _ in range(MAX_SILENCE_REMINDERS):
        last = plan_turn(
            interaction="reminder_required",
            user_text="",
            session=session,
            decision=decision,
            user_name="Alex",
        )
    assert last is not None
    assert last.speak == SILENCE_BYE
    assert last.end_call is True


def test_goodbye_ends_in_character():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    out = plan_turn(
        interaction="response_required",
        user_text="Alright, goodbye",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert out.speak == GOODBYE_FAMILY
    assert out.end_call is True
    assert out.need_twin is False


def test_family_can_leave_a_message_mid_call():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    ask = plan_turn(
        interaction="response_required",
        user_text="Can you take a message?",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert ask.speak == MESSAGE_KEEP
    kept = plan_turn(
        interaction="response_required",
        user_text="Tell them I stopped by the farm.",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert kept.save_message.startswith("Tell them")
    assert kept.speak == MESSAGE_GOT
    assert kept.end_call is False
    assert session.phase == "talking"


def test_unknown_message_policy_keeps_then_hangs_up():
    decision = decide_inbound("+15550001111", _family(unknown_policy="message"))
    session = _session(decision)
    prompt = plan_turn(
        interaction="response_required",
        user_text="",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert prompt.speak == MESSAGE_PROMPT
    thanks = plan_turn(
        interaction="response_required",
        user_text="Please call me back about Sunday.",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert thanks.speak == MESSAGE_THANKS
    assert thanks.end_call is True
    assert "Sunday" in thanks.save_message


def test_decline_does_not_greet():
    decision = decide_inbound("+15550001111", _family())
    session = _session(decision)
    out = plan_turn(
        interaction="response_required",
        user_text="",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert out.speak == DECLINE_SPOKEN
    assert out.end_call is True


def test_handoff_open_and_closed():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    closed = plan_turn(
        interaction="response_required",
        user_text="Can you put me through?",
        session=session,
        decision=decision,
        settings=_family(),
        user_name="Alex",
    )
    assert closed.speak == HANDOFF_CLOSED
    open_settings = _family(handoff_enabled=True, handoff_e164="+15557770000")
    session2 = _session(decision, greeted=True)
    opened = plan_turn(
        interaction="response_required",
        user_text="Please transfer me",
        session=session2,
        decision=decision,
        settings=open_settings,
        user_name="Alex",
    )
    assert opened.speak == HANDOFF_SPOKEN
    assert opened.transfer_number == "+15557770000"


def test_poor_audio_then_offer_a_message():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    first = plan_turn(
        interaction="response_required",
        user_text="uh",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert first.speak == UNCLEAR_SPOKEN
    second = plan_turn(
        interaction="response_required",
        user_text="hmm",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert second.speak == UNCLEAR_OFFER
    assert second.need_twin is False


def test_angry_caller_stays_calm():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    out = plan_turn(
        interaction="response_required",
        user_text="This is ridiculous, shut up",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert out.speak == ANGRY_CALM
    assert out.need_twin is False


def test_angry_question_still_goes_to_the_twin():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    out = plan_turn(
        interaction="response_required",
        user_text="Where the hell did you grow up?",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert out.need_twin is True


def test_duplicate_utterance_does_not_reask_the_brain():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True, last_user="How was the farm")
    out = plan_turn(
        interaction="response_required",
        user_text="How was the farm",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert out.speak == LISTENING
    assert out.need_twin is False


def test_ordinary_talk_requests_the_twin():
    decision = decide_inbound("+15551230000", _family())
    session = _session(decision, greeted=True)
    out = plan_turn(
        interaction="response_required",
        user_text="Where did you grow up?",
        session=session,
        decision=decision,
        user_name="Alex",
    )
    assert out.need_twin is True
    assert out.speak == ""


def test_intent_helpers():
    assert wants_goodbye("ok bye")
    assert wants_goodbye("that's all for now")
    assert not wants_goodbye("how was the farm")
    assert wants_message("can you take a message")
    assert wants_message("tell them I called")
    assert not wants_message("what do you remember")
    assert sounds_unclear("uh")
    assert not sounds_unclear("Hey Alex")
    assert sounds_angry("go to hell")
    assert not sounds_angry("I missed you")


def test_notify_copy_plain_language():
    title, body = notify_copy(direction="inbound", who="Sam")
    assert title == "Phone"
    assert body == "Sam called. Transcript is in Phone."
    _, left = notify_copy(direction="inbound", who="Sam", message_left="Call me Sunday.")
    assert "left a message" in left
    _, declined = notify_copy(direction="inbound", who="+15550001111", status="decline")
    assert "didn't take it" in declined
    who = caller_display("+15551230000", _family())
    assert who == "Sam"


def test_phone_addendum_stays_in_character():
    blob = phone_system_addendum("Sam")
    assert "speaking with Sam" in blob
    assert "receptionist" in blob
    assert "Do not file this call" in blob
    assert wants_handoff("can you put me through")
    assert not wants_handoff("I couldn't reach you last week")
