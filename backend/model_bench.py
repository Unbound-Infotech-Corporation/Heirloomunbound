"""Benchmark local Ollama chat models for the hardware tiers (docs/MODEL-TIERS.md).

  heirloom-box bench-models MODEL [MODEL ...] [--ollama URL] [--out FILE]
  python -m model_bench qwen3.5:9b --ollama http://192.168.0.60:11434 --out /tmp/bench.jsonl

Each model answers the same fixed checks, scored without any judge model:
  grounding  the real classifier, claim checker and card-only answer from grounding.py
  chat       normal assistant requests with checkable answers
  tools      Ollama tool calls: right tool, usable arguments, no tool for small talk
  json       schema-constrained extraction
  speed      cold load, time to first token, tokens per second, VRAM at the tier context

Nothing about the owner is used. The only "memory" is the labeled eval card from
box_eval_grounding. Local Ollama only; a cloud tag is refused.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from box_eval_grounding import CARD_STORY, CARD_TITLE, LIFE_QUESTIONS, OVERBLOCK, RECALL, embellished_words, mentions_card
from model_tiers import is_cloud_tag, think_value

CARD = {"card_id": "bench-card", "title": CARD_TITLE, "story": CARD_STORY, "era": "1978", "people": []}
CARDS = [
    CARD,
    {"card_id": "bench-dog", "title": "heirloom-eval family dog", "era": "1980s", "people": [],
     "story": "Our family dog was named Rusty. He slept by the woodstove every winter."},
    {"card_id": "bench-song", "title": "heirloom-eval wedding song", "era": "1975", "people": ["Linda"],
     "story": "Linda and I danced to Unchained Melody at our wedding in 1975."},
]
MULTI_RECALL = [
    ("What was our family dog's name?", ("rusty",)),
    ("What song did Linda and I dance to at our wedding?", ("unchained",)),
    ("Who did I marry?", ("linda",)),
]
MULTI_DECLINE = [
    "What breed was Rusty?",
    "Where was our wedding held?",
    "What color was Linda's dress?",
    "How old was I when I got my first car?",
    "What did Rusty like to eat?",
]

NOT_PERSONAL = [
    "Hi, how are you today?",
    "What's a good recipe for banana bread?",
    "Can you explain how a heat pump works?",
    "What should I get my wife for our anniversary?",
    "Give me three tips for sleeping better.",
    "Is it going to be cold enough to frost tonight where tomatoes grow?",
    "How long should I boil an egg?",
    "Write a thank-you note to my neighbor for the pie.",
    "What's the capital of Australia?",
    "Help me plan a small birthday party for my son.",
    "How do I change a flat tire?",
    "Tell me a joke about fishing.",
]

ASSISTANT_SYSTEM = (
    "You are Heirloom, a warm, capable personal assistant running privately on the owner's own computer. "
    "Answer directly and helpfully. When asked to write something, write it right away. Keep answers concise."
)

CHAT_TASKS: list[tuple[str, Callable[[str], bool]]] = [
    ("What's 15% of 80?", lambda t: bool(re.search(r"\b12(\.0+)?\b", t))),
    ("Help me write a short birthday note for my sister.",
     lambda t: "birthday" in t.lower() and len(t) >= 80 and not t.strip().lower().startswith(("what", "could you tell", "sure! what"))),
    ("My printer won't connect to wifi. What should I try?",
     lambda t: len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*\u2022])\s+", t)) >= 3 and re.search(r"(?i)restart|reboot|router|power", t) is not None),
    ("Plan my week: gym three times and a dentist visit.",
     lambda t: "dentist" in t.lower() and len(set(re.findall(r"(?i)\b(mon|tues|wednes|thurs|fri|satur|sun)day\b", t.lower()))) >= 3),
    ("A train leaves at 2:45 PM and the trip takes 3 hours 50 minutes. What time does it arrive?",
     lambda t: "6:35" in t),
    ("Convert 350 degrees Fahrenheit to Celsius, rounded to the nearest whole number.",
     lambda t: "177" in t),
    ("List three vegetables that grow well in partial shade. Reply with exactly three bullet points and nothing else.",
     lambda t: len([line for line in t.strip().splitlines() if line.strip()]) == 3
     and all(re.match(r"\s*(?:[-*\u2022]|\d+[.)])\s+\S", line) for line in t.strip().splitlines() if line.strip())),
    ("Summarize in one sentence: Dr. Patel's office called. Your Tuesday appointment moved to Thursday at 3 pm. "
     "Please bring your new insurance card and arrive 15 minutes early to fill out forms.",
     lambda t: all(word in t.lower() for word in ("thursday", "patel", "insurance")) and len(re.findall(r"[.!?](\s|$)", t.strip())) <= 2),
    ("I have 4 cartons of 12 eggs and I use 7 eggs. How many eggs are left?", lambda t: bool(re.search(r"\b41\b", t))),
    ("Write a two-sentence text to my neighbor asking to borrow a ladder on Saturday.",
     lambda t: "ladder" in t.lower() and "saturday" in t.lower() and len(t) < 500),
    ("What should I do if an adult is choking?",
     lambda t: re.search(r"(?i)heimlich|abdominal thrust|back blow", t) is not None and re.search(r"911|emergency", t) is not None),
    ("Translate to Spanish: Where is the library?", lambda t: "biblioteca" in t.lower()),
    ("I'm meeting friends at 7:15 PM. The drive takes 25 minutes, parking takes 10, and I want to be 5 minutes early. "
     "What's the latest time I can leave?", lambda t: "6:35" in t),
    ("My grandson is three times as old as he was 8 years ago. How old is he now?", lambda t: bool(re.search(r"\b12\b", t))),
    ("Which is larger, 9.11 or 9.9?", lambda t: bool(re.search(r"9\.9\b(?!\d)", t.split("\n")[0] if t else "")) or
     bool(re.search(r"(?i)9\.9 is (larger|bigger|greater)", t))),
    ("How many times does the letter r appear in the word strawberry?", lambda t: bool(re.search(r"\b(3|three)\b", t.lower()))),
    ("Write a haiku about autumn leaves. Reply with only the three lines of the haiku.",
     lambda t: len([line for line in t.strip().splitlines() if line.strip()]) == 3),
    ("Explain what a Roth IRA is to a 70-year-old in under 60 words.",
     lambda t: len(t.split()) <= 60 and "tax" in t.lower()),
    ("Give me a packing list for a weekend camping trip: exactly 5 numbered items, then one sentence of advice.",
     lambda t: len(re.findall(r"(?m)^\s*\d+[.)]\s+\S", t)) == 5),
]

LONG_NOTE_FACT = "The plumber, Gary from Reliable Pipes, is coming on Thursday between 1 and 3 pm."


def _long_note() -> str:
    filler = []
    chores = ["buy dog food", "return library books", "call the bank about the card", "pick up the dry cleaning",
              "schedule the oil change", "water the ferns", "pay the electric bill", "book the haircut",
              "renew the car registration", "order printer ink"]
    for index in range(60):
        filler.append(f"Note {index + 1}: remember to {chores[index % len(chores)]} and check the mail before noon.")
    filler.insert(37, LONG_NOTE_FACT)
    return "\n".join(filler)


MULTI_TURN_CHAT: list[tuple[list[dict], Callable[[str], bool]]] = [
    ([{"role": "user", "content": "Quick heads up: I'm vegetarian and I don't eat eggs."},
      {"role": "assistant", "content": "Got it, vegetarian and no eggs."},
      {"role": "user", "content": "Suggest one easy dinner I could make tonight, with the ingredient list."}],
     lambda t: not re.search(r"(?i)\b(chicken|beef|pork|bacon|fish|salmon|shrimp|egg|eggs|turkey|sausage|ham|tuna)\b", t)
     and len(t) > 80),
    ([{"role": "user", "content": _long_note() + "\n\nFrom my notes above: when is the plumber coming, and who is it?"}],
     lambda t: "thursday" in t.lower() and "gary" in t.lower()),
]

TOOLS = [
    {"type": "function", "function": {"name": "set_reminder", "description": "Save a reminder for the owner.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "when": {"type": "string", "description": "When, in the owner's words or ISO time"}},
                    "required": ["text", "when"]}}},
    {"type": "function", "function": {"name": "get_weather", "description": "Current weather for a place.",
     "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}}},
    {"type": "function", "function": {"name": "search_files", "description": "Search the owner's local documents and files.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "create_calendar_event", "description": "Add an event to the owner's calendar.",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "start": {"type": "string"},
                                                     "duration_minutes": {"type": "integer"}}, "required": ["title", "start"]}}},
    {"type": "function", "function": {"name": "draft_email", "description": "Create an email draft. Never sends.",
     "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
                    "required": ["to", "body"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the public web for fresh information.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]


def _has(args: dict, key: str, *words: str) -> bool:
    value = str(args.get(key) or "").lower()
    return bool(value) and all(word in value for word in words)


TOOL_CASES: list[tuple[str, Callable[[list[dict]], bool]]] = [
    ("Remind me to call the pharmacy tomorrow at 10am.",
     lambda c: len(c) == 1 and c[0]["name"] == "set_reminder" and _has(c[0]["args"], "text", "pharmacy") and "10" in str(c[0]["args"].get("when"))),
    ("What's the weather in Portland right now?",
     lambda c: len(c) == 1 and c[0]["name"] == "get_weather" and _has(c[0]["args"], "location", "portland")),
    ("Find my tax documents from 2024.",
     lambda c: len(c) == 1 and c[0]["name"] == "search_files" and _has(c[0]["args"], "query", "tax")),
    ("Put lunch with Sarah on my calendar Friday at noon for an hour.",
     lambda c: len(c) == 1 and c[0]["name"] == "create_calendar_event" and "sarah" in str(c[0]["args"].get("title", "")).lower()
     and str(c[0]["args"].get("duration_minutes", "60")).strip() in {"60", "60.0"}),
    ("Draft an email to bob@example.com saying I'll be ten minutes late to the meeting.",
     lambda c: len(c) == 1 and c[0]["name"] == "draft_email" and _has(c[0]["args"], "to", "bob@example.com") and "late" in str(c[0]["args"].get("body", "")).lower()),
    ("Hi! How's your day going?", lambda c: not c),
    ("Thanks, that's all for now.", lambda c: not c),
    ("Look up the latest news about the Artemis moon mission.",
     lambda c: len(c) == 1 and c[0]["name"] == "web_search" and _has(c[0]["args"], "query", "artemis")),
    ("Remind me to take my pills every morning at 8, and put a dentist appointment on my calendar December 3 at 2pm.",
     lambda c: sorted(x["name"] for x in c) == ["create_calendar_event", "set_reminder"]),
    ("What's the weather where my daughter lives? She moved to Austin last year.",
     lambda c: len(c) == 1 and c[0]["name"] == "get_weather" and _has(c[0]["args"], "location", "austin")),
    ("Email my doctor and ask if I can move my appointment.",
     lambda c: not any("@" in str(x["args"].get("to", "")) for x in c if x.get("name") == "draft_email")),
    ("Find my home insurance policy in my files, and look up current 30-year mortgage rates online.",
     lambda c: sorted(x["name"] for x in c) == ["search_files", "web_search"]),
]

JSON_CASES: list[tuple[str, dict, Callable[[dict], bool]]] = [
    ("Extract the contact. Message: 'Hey it's Maria Lopez, call me back at 555-201-3344 about Tuesday.'",
     {"type": "object", "properties": {"name": {"type": "string"}, "phone": {"type": "string"}, "day": {"type": "string"}},
      "required": ["name", "phone", "day"]},
     lambda d: "maria" in str(d.get("name")).lower() and re.sub(r"\D", "", str(d.get("phone"))) == "5552013344" and "tue" in str(d.get("day")).lower()),
    ("Make a shopping list from: 'We need 2 gallons of milk, a dozen eggs and 3 avocados.'",
     {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
         "name": {"type": "string"}, "quantity": {"type": "number"}}, "required": ["name", "quantity"]}}}, "required": ["items"]},
     lambda d: sorted(int(float(i.get("quantity", 0))) for i in d.get("items", []) if isinstance(i, dict)) == [2, 3, 12]),
    ("Turn this story into a memory card: 'In the summer of 1969 my brother Tom and I drove our dad's pickup to Yellowstone and slept in the truck bed.'",
     {"type": "object", "properties": {"title": {"type": "string"}, "people": {"type": "array", "items": {"type": "string"}},
                                       "era": {"type": "string"}, "place": {"type": "string"}}, "required": ["title", "people", "era", "place"]},
     lambda d: any("tom" in str(p).lower() for p in d.get("people", [])) and "1969" in str(d.get("era")) and "yellowstone" in str(d.get("place")).lower()),
    ("Rate each review as positive, negative or neutral: 1) 'Loved it, will buy again.' 2) 'Broke after one day.' 3) 'It arrived on Monday.'",
     {"type": "object", "properties": {"ratings": {"type": "array", "items": {"type": "string", "enum": ["positive", "negative", "neutral"]}}},
      "required": ["ratings"]},
     lambda d: [str(x).lower() for x in d.get("ratings", [])] == ["positive", "negative", "neutral"]),
    ("Today is Wednesday 2026-11-25. Parse the reminder: 'water the plants next Monday at 8am'.",
     {"type": "object", "properties": {"what": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
                                       "time": {"type": "string", "description": "HH:MM 24h"}}, "required": ["what", "date", "time"]},
     lambda d: "plant" in str(d.get("what")).lower() and str(d.get("date")).startswith("2026-11-30") and str(d.get("time")).startswith("08:00")),
    ("From this voicemail, list every person mentioned with their relationship to me: 'Hi Dad, it's Kelly. Mom says hi. "
     "Uncle Joe and his wife Barb are coming Sunday, and my son Eli wants to show you his science project.'",
     {"type": "object", "properties": {"people": {"type": "array", "items": {"type": "object", "properties": {
         "name": {"type": "string"}, "relationship": {"type": "string"}}, "required": ["name", "relationship"]}}}, "required": ["people"]},
     lambda d: (lambda rows: {"kelly", "joe", "barb", "eli"} <= set(rows)
                and "daughter" in rows.get("kelly", "") and "grand" in rows.get("eli", "") and "brother" not in rows.get("barb", ""))(
         {str(p.get("name", "")).lower().split()[-1] if str(p.get("name", "")).lower().startswith(("uncle", "aunt")) else str(p.get("name", "")).lower().split()[0]:
          str(p.get("relationship", "")).lower() for p in d.get("people", []) if isinstance(p, dict) and str(p.get("name", "")).strip()})),
    ("Today is Wednesday 2026-11-25. Parse: 'dinner with the Hendersons the Friday after next at 6:30pm for two hours'.",
     {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string", "description": "YYYY-MM-DD"},
                                       "start": {"type": "string", "description": "HH:MM 24h"}, "end": {"type": "string", "description": "HH:MM 24h"}},
      "required": ["title", "date", "start", "end"]},
     lambda d: str(d.get("date")).startswith("2026-12-04") and str(d.get("start")).startswith("18:30") and str(d.get("end")).startswith("20:30")),
]

VERIFY_CASES: list[tuple[str, list[str], set[int]]] = [
    ("My first car was a blue 1978 Chevy Nova.", [], set()),
    ("My first car was a blue 1978 Chevy Nova. My dad helped me pick it out at a lot in Dayton.", [], {2}),
    ("I paid $800 for my first car. We drove it to Lake Tahoe every summer.", [], {2}),
    ("My mom's name was Linda.", [], {1}),
    ("Happy birthday, sis! I hope your day is full of good things.", ["Help me write a short birthday note for my sister."], set()),
    ("I bought a blue Chevy Nova for $800. It was red with a white stripe and I named it Betsy.", [], {2}),
]


def _post(url: str, body: dict, timeout: float = 300.0) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (LAN Ollama)
        return json.loads(response.read().decode("utf-8") or "{}")


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8") or "{}")


class Bench:
    def __init__(self, base: str, model: str, num_ctx: int):
        self.base = base.rstrip("/")
        self.model = model
        self.num_ctx = num_ctx
        self.think = think_value(model, self.base)
        try:
            self.caps = list(_post(self.base + "/api/show", {"model": model}).get("capabilities") or [])
        except Exception:  # noqa: BLE001
            self.caps = []

    def chat(self, messages: list[dict], *, tools: Optional[list] = None, fmt: Any = None,
             num_predict: int = 700, temperature: float = 0.2) -> tuple[dict, float]:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False,
                                "options": {"temperature": temperature, "num_predict": num_predict}}
        if self.think is not None:
            body["think"] = self.think
        if tools:
            body["tools"] = tools
        if fmt is not None:
            body["format"] = fmt
        began = time.perf_counter()
        data = _post(self.base + "/api/chat", body)
        return data, time.perf_counter() - began

    def stream_latency(self, prompt: str, extra: Optional[dict] = None) -> dict:
        body: dict[str, Any] = {"model": self.model, "stream": True,
                                "messages": [{"role": "system", "content": ASSISTANT_SYSTEM}, {"role": "user", "content": prompt}],
                                "options": {"temperature": 0.2, "num_predict": 400, **(extra or {})}}
        if self.think is not None:
            body["think"] = self.think
        request = urllib.request.Request(self.base + "/api/chat", data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
        began = time.perf_counter()
        first = None
        final: dict = {}
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            for raw in response:
                line = json.loads(raw.decode("utf-8") or "{}")
                if first is None and str((line.get("message") or {}).get("content") or "").strip():
                    first = time.perf_counter() - began
                if line.get("done"):
                    final = line
        total = time.perf_counter() - began
        evals = int(final.get("eval_count") or 0)
        eval_s = float(final.get("eval_duration") or 0) / 1e9
        return {"ttft_s": round(first or total, 2), "total_s": round(total, 2),
                "tok_s": round(evals / eval_s, 1) if eval_s else 0.0, "tokens": evals}


def _text(data: dict) -> str:
    return str((data.get("message") or {}).get("content") or "").strip()


def _calls(data: dict) -> list[dict]:
    rows = []
    for call in (data.get("message") or {}).get("tool_calls") or []:
        fn = call.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        rows.append({"name": str(fn.get("name") or ""), "args": args if isinstance(args, dict) else {}})
    return rows


def _unload(base: str, model: str) -> None:
    try:
        _post(base + "/api/generate", {"model": model, "prompt": "", "keep_alive": 0}, timeout=60)
    except Exception:  # noqa: BLE001
        pass


def _loaded(base: str, model: str) -> dict:
    for row in _get(base + "/api/ps").get("models") or []:
        if row.get("name") == model or row.get("model") == model:
            return row
    return {}


async def grounding_checks(bench: Bench, log: Callable[[str], None]) -> dict:
    """The production grounding functions, pointed at this model."""
    os.environ["OLLAMA_BASE_URL"] = bench.base
    os.environ["OLLAMA_TWIN_MODEL"] = bench.model
    import grounding
    from memory_cards import NO_MEMORY_YET

    out: dict[str, Any] = {}
    # 1. Classifier, asked directly (the keyword gate in front of it does not depend on the model).
    right = errors = 0
    wrong: list[str] = []
    timings: list[float] = []
    for question, want in [(q, True) for q in LIFE_QUESTIONS] + [(q, False) for q in NOT_PERSONAL]:
        began = time.perf_counter()
        try:
            answer = await grounding.ask_box_model(grounding.CLASSIFY_SYSTEM, f"Message: {question}", json_mode=True,
                                                   num_predict=16, timeout=60)
            value = grounding._json_object(answer).get("personal")
            if isinstance(value, str):
                value = value.strip().lower() in {"true", "yes", "1"}
            ok = value is want
        except Exception:  # noqa: BLE001
            errors += 1
            ok = False
        timings.append(time.perf_counter() - began)
        right += ok
        if not ok:
            wrong.append(question)
    total = len(LIFE_QUESTIONS) + len(NOT_PERSONAL)
    out["classifier"] = {"right": right, "of": total, "errors": errors, "wrong": wrong,
                         "median_s": round(statistics.median(timings), 2)}
    log(f"    classifier {right}/{total} errors={errors}")
    # 2. Claim checker.
    good = 0
    detail = []
    for reply, said, bad in VERIFY_CASES:
        verdict = await grounding.verify_reply(reply, cards=[CARD], owner_messages=said)
        sentences = grounding.split_sentences(reply)
        removed = {index for index, line in enumerate(sentences, 1) if line in verdict.removed}
        ok = removed == bad and verdict.source != "fail-closed"
        good += ok
        detail.append({"reply": reply[:60], "want": sorted(bad), "got": sorted(removed), "source": verdict.source})
    out["verifier"] = {"right": good, "of": len(VERIFY_CASES), "detail": detail}
    log(f"    verifier {good}/{len(VERIFY_CASES)}")
    # 3. Card-only answers: recall the card, decline everything else.
    recall_ok = 0
    padding: list[int] = []
    for question in RECALL:
        got = await grounding.answer_personal(question, cards=[CARD], owner_messages=[question], name="the owner")
        hit = mentions_card(got["reply"]) and bool(got["cited"])
        recall_ok += hit
        padding.append(len(embellished_words(got["reply"])))
    declined = 0
    invented: list[str] = []
    for question in LIFE_QUESTIONS:
        got = await grounding.answer_personal(question, cards=[CARD], owner_messages=[question], name="the owner")
        if got["reply"] == NO_MEMORY_YET or not got["cited"]:
            declined += 1
        else:
            invented.append(f"{question} -> {got['reply'][:80]}")
    for question, words in MULTI_RECALL:
        got = await grounding.answer_personal(question, cards=CARDS, owner_messages=[question], name="the owner")
        recall_ok += all(word in got["reply"].lower() for word in words) and bool(got["cited"])
    for question in MULTI_DECLINE:
        got = await grounding.answer_personal(question, cards=CARDS, owner_messages=[question], name="the owner")
        reply = got["reply"]
        # Restating what the card says is fine; adding a breed, place, color, age or food is not.
        added = re.search(r"(?i)\b(beagle|lab|retriever|shepherd|terrier|collie|church|chapel|hall|park|white|ivory|blue|red|"
                          r"\d{2} years|teen|sixteen|seventeen|eighteen|kibble|bones?|scraps|steak|chicken)\b", reply)
        if reply == NO_MEMORY_YET or not got["cited"] or not added:
            declined += 1
        else:
            invented.append(f"{question} -> {reply[:80]}")
    out["recall"] = {"right": recall_ok, "of": len(RECALL) + len(MULTI_RECALL), "padding_words": padding}
    out["decline"] = {"right": declined, "of": len(LIFE_QUESTIONS) + len(MULTI_DECLINE), "invented": invented}
    log(f"    recall {recall_ok}/{out['recall']['of']} decline {declined}/{out['decline']['of']}")
    return out


def run_model(base: str, model: str, num_ctx: int, log: Callable[[str], None]) -> dict:
    if is_cloud_tag(model):
        raise SystemExit(f"refusing cloud model {model}")
    for row in _get(base + "/api/ps").get("models") or []:
        _unload(base, str(row.get("name")))
    bench = Bench(base, model, num_ctx)
    result: dict[str, Any] = {"model": model, "caps": bench.caps, "think": bench.think,
                              "at": datetime.now(timezone.utc).isoformat()}
    began = time.perf_counter()
    loaded = _post(base + "/api/generate", {"model": model, "prompt": "", "keep_alive": "15m"}, timeout=900)
    result["load_s"] = round(float(loaded.get("load_duration") or 0) / 1e9 or (time.perf_counter() - began), 1)
    row = _loaded(base, model)
    result["default_ctx"] = row.get("context_length")
    result["vram_mib_default_ctx"] = int(row.get("size_vram") or 0) // (1024 * 1024)
    result["size_mib_default_ctx"] = int(row.get("size") or 0) // (1024 * 1024)
    log(f"  {model}: loaded {result['load_s']}s ctx={result['default_ctx']} vram={result['vram_mib_default_ctx']}MiB think={bench.think}")

    # Speed
    speed = [bench.stream_latency(prompt) for prompt in ("Hi, how are you today?", OVERBLOCK[1], OVERBLOCK[3])]
    result["speed"] = {"ttft_s": statistics.median(s["ttft_s"] for s in speed),
                       "total_s": statistics.median(s["total_s"] for s in speed),
                       "tok_s": statistics.median(s["tok_s"] for s in speed), "runs": speed}
    log(f"    speed ttft {result['speed']['ttft_s']}s total {result['speed']['total_s']}s {result['speed']['tok_s']} tok/s")

    # Chat
    passed, failed, chat_s = 0, [], []
    for prompt, check in CHAT_TASKS:
        try:
            data, secs = bench.chat([{"role": "system", "content": ASSISTANT_SYSTEM}, {"role": "user", "content": prompt}])
            ok = check(_text(data))
        except Exception as exc:  # noqa: BLE001
            ok, secs = False, 0.0
            data = {"message": {"content": f"ERROR {exc}"}}
        chat_s.append(secs)
        passed += ok
        if not ok:
            failed.append(f"{prompt[:50]} -> {_text(data)[:160]!r}")
    for turns, check in MULTI_TURN_CHAT:
        try:
            data, secs = bench.chat([{"role": "system", "content": ASSISTANT_SYSTEM}] + turns)
            ok = check(_text(data))
        except Exception as exc:  # noqa: BLE001
            ok, secs = False, 0.0
            data = {"message": {"content": f"ERROR {exc}"}}
        chat_s.append(secs)
        passed += ok
        if not ok:
            failed.append(f"{turns[-1]['content'][-50:]} -> {_text(data)[:160]!r}")
    total_chat = len(CHAT_TASKS) + len(MULTI_TURN_CHAT)
    result["chat"] = {"right": passed, "of": total_chat, "failed": failed, "median_s": round(statistics.median(chat_s), 2)}
    log(f"    chat {passed}/{total_chat}")

    # Tools
    if "tools" in bench.caps:
        passed, failed = 0, []
        for prompt, check in TOOL_CASES:
            system = "You are Heirloom, a personal assistant. Use a tool only when the request needs one. Today is Wednesday, November 25, 2026."
            try:
                data, _ = bench.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], tools=TOOLS, temperature=0.0)
                calls = _calls(data)
                ok = check(calls)
            except Exception as exc:  # noqa: BLE001
                ok, calls = False, [{"error": str(exc)[:120]}]
            passed += ok
            if not ok:
                failed.append(f"{prompt[:40]} -> {json.dumps(calls)[:200]}")
        result["tools"] = {"right": passed, "of": len(TOOL_CASES), "failed": failed}
    else:
        result["tools"] = {"right": 0, "of": len(TOOL_CASES), "failed": ["no tools capability"]}
    log(f"    tools {result['tools']['right']}/{len(TOOL_CASES)}")

    # JSON
    passed, failed = 0, []
    for prompt, schema, check in JSON_CASES:
        data = {}
        try:
            data, _ = bench.chat([{"role": "system", "content": "Reply with JSON only."}, {"role": "user", "content": prompt}],
                                 fmt=schema, temperature=0.0)
            parsed = json.loads(_text(data))
            ok = isinstance(parsed, dict) and check(parsed)
        except Exception:  # noqa: BLE001
            ok = False
        passed += ok
        if not ok:
            failed.append(f"{prompt[:40]} -> {_text(data)[:160] if isinstance(data, dict) else ''}")
    result["json"] = {"right": passed, "of": len(JSON_CASES), "failed": failed}
    log(f"    json {passed}/{len(JSON_CASES)}")

    # Grounding (production prompts)
    result["grounding"] = asyncio.run(grounding_checks(bench, log))

    # VRAM at fixed tier contexts (each is one reload).
    sizes = {}
    for ctx in (8192, 16384, 32768):
        try:
            _unload(base, model)
            _post(base + "/api/generate", {"model": model, "prompt": "", "keep_alive": "2m", "options": {"num_ctx": ctx}}, timeout=900)
            row = _loaded(base, model)
            sizes[str(ctx)] = {"vram_mib": int(row.get("size_vram") or 0) // (1024 * 1024), "size_mib": int(row.get("size") or 0) // (1024 * 1024)}
        except Exception as exc:  # noqa: BLE001
            sizes[str(ctx)] = {"error": str(exc)[:120]}
    result["vram_by_ctx"] = sizes
    log(f"    vram by ctx {sizes}")
    _unload(base, model)
    result["score"] = score(result)
    log(f"    SCORE {result['score']}")
    return result


def _frac(block: dict) -> float:
    return (block.get("right", 0) / block["of"]) if block.get("of") else 0.0


def score(result: dict) -> dict:
    """Quality out of 100. Grounding weighs most: a twin that invents a life is worse than a slow one."""
    g = result.get("grounding") or {}
    grounding_part = 0.15 * _frac(g.get("classifier", {})) + 0.25 * _frac(g.get("verifier", {})) \
        + 0.25 * _frac(g.get("recall", {})) + 0.35 * _frac(g.get("decline", {}))
    quality = 40 * grounding_part + 30 * _frac(result.get("chat", {})) + 18 * _frac(result.get("tools", {})) \
        + 12 * _frac(result.get("json", {}))
    return {"quality": round(quality, 1), "grounding": round(100 * grounding_part, 1)}


def cpu_speed(base: str, model: str, threads: int = 8) -> dict:
    """Speed with no GPU layers (num_gpu 0), as on a PC without a supported card."""
    for row in _get(base + "/api/ps").get("models") or []:
        _unload(base, str(row.get("name")))
    bench = Bench(base, model, 8192)
    extra = {"num_gpu": 0, "num_thread": threads, "num_ctx": 8192}
    runs = [bench.stream_latency(prompt, extra) for prompt in ("Hi, how are you today?", OVERBLOCK[1], OVERBLOCK[3])]
    _unload(base, model)
    return {"model": model, "cpu_threads": threads, "cpu_ttft_s": statistics.median(r["ttft_s"] for r in runs),
            "cpu_total_s": statistics.median(r["total_s"] for r in runs), "cpu_tok_s": statistics.median(r["tok_s"] for r in runs)}


def main(argv: list[str]) -> int:
    args = list(argv)
    base = os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    out = ""
    num_ctx = 16384
    models: list[str] = []
    while args:
        item = args.pop(0)
        if item == "--ollama" and args:
            base = args.pop(0)
        elif item == "--out" and args:
            out = args.pop(0)
        elif item == "--ctx" and args:
            num_ctx = int(args.pop(0))
        elif item == "--cpu-speed":
            num_ctx = -1
        else:
            models.append(item)
    if not models:
        print(__doc__)
        return 2

    def log(line: str) -> None:
        print(line, flush=True)

    for model in models:
        try:
            result = cpu_speed(base, model) if num_ctx == -1 else run_model(base, model, num_ctx, log)
            if num_ctx == -1:
                log(f"  {model}: {result}")
        except Exception as exc:  # noqa: BLE001
            result = {"model": model, "error": str(exc)[:300]}
            log(f"  {model}: ERROR {exc}")
        if out:
            with open(out, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
