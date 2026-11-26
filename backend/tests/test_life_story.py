"""Step 3: life-story interview and memory imports. No network, no Mongo, no Ollama."""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import types

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom")

if "deps" not in sys.modules:
    try:
        import deps  # noqa: F401  (full API install)
    except Exception:  # noqa: BLE001 - CI installs requirements-ci.txt only
        _stub = types.ModuleType("deps")
        _stub.db = None
        _stub.get_current_user = None
        _stub.EMERGENT_LLM_KEY = ""
        sys.modules["deps"] = _stub

import pytest  # noqa: E402

import life_story as ls  # noqa: E402
import memory_cards as mc  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- fake Mongo

def _match(doc: dict, query: dict) -> bool:
    for key, want in (query or {}).items():
        have = doc.get(key)
        if isinstance(want, dict) and "$in" in want:
            if have not in want["$in"]:
                return False
        elif have != want:
            return False
    return True


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction=1):
        self.rows.sort(key=lambda r: str(r.get(key) or ""), reverse=direction < 0)
        return self

    async def to_list(self, n):
        return self.rows[:n]


class _Result:
    def __init__(self, n):
        self.deleted_count = n


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    def find(self, query=None, projection=None):
        return _Cursor([{k: v for k, v in d.items() if k != "_id"} for d in self.docs if _match(d, query or {})])

    async def find_one(self, query, projection=None):
        for d in self.docs:
            if _match(d, query):
                return dict(d)
        return None

    async def find_one_and_delete(self, query):
        for d in list(self.docs):
            if _match(d, query):
                self.docs.remove(d)
                return d
        return None

    async def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _match(d, query):
                d.update(update.get("$set") or {})
                return
        if upsert:
            self.docs.append({**query, **(update.get("$set") or {})})

    async def delete_one(self, query):
        for d in list(self.docs):
            if _match(d, query):
                self.docs.remove(d)
                return _Result(1)
        return _Result(0)

    async def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))


class FakeDb:
    def __init__(self):
        self._c: dict[str, FakeCollection] = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._c.setdefault(name, FakeCollection())

async def fake_complete(system: str, user: str) -> str:
    if system == mc.CARD_SYSTEM:
        answer = user.split("Answer:\n", 1)[-1]
        return json.dumps({"title": answer.split(".")[0][:60], "era": "", "people": ["Ray", "Zelda"], "story": answer})
    if system == ls.FOLLOWUP_SYSTEM:
        return "What was Uncle Ray like when he took you fishing?"
    return ""


# ---------------------------------------------------------------- interview plan

def test_interview_fits_thirty_to_sixty_minutes():
    full, short = ls.plan("full"), ls.plan("short")
    assert 30 <= ls.estimate_minutes(len(full)) <= 60
    assert 20 <= ls.estimate_minutes(len(short)) <= 35
    assert ls.estimate_minutes(len(full) + ls.MAX_FOLLOWUPS) <= 65
    assert len({row["qid"] for row in full}) == len(full)
    # Generic buyer: no question assumes a son, a wife, or a religion.
    text = " ".join(row["question"].lower() for row in full)
    for word in (" your son", " your wife", " your husband", " church"):
        assert word not in text


def test_session_walks_skips_and_finishes():
    s = ls.new_session("u", "short")
    first = ls.current_item(s)
    assert first["qid"] == "roots.1"
    ls.mark(s, "roots.1", "answered", "card_1")
    assert ls.current_item(s)["qid"] == "roots.2"
    ls.skip_chapter(s, "roots")
    assert ls.current_item(s)["chapter"] == "family"
    p = ls.progress(s)
    assert p["answered"] == 1 and p["remaining"] == p["total"] - 2
    assert p["chapters"][0] == {"key": "roots", "title": "Where you come from", "total": 2, "done": 2}
    for item in list(s["queue"]):
        if item["qid"] not in s["done"]:
            ls.mark(s, item["qid"], "skipped")
    assert s["status"] == "finished" and ls.current_item(s) is None


def test_followups_only_ask_about_what_they_said():
    answer = "My uncle Ray took me fishing at Lake Tahoe every summer in his old boat."
    assert ls.followup_from_model(answer, "What was Ray's boat like?") == "What was Ray's boat like?"
    assert ls.followup_from_model(answer, "What did your sister Margaret think of the boat?") is None  # invented name
    assert ls.followup_from_model(answer, "How did that make you feel about life?") is None  # nothing from the answer
    assert ls.followup_from_model(answer, "NONE") is None
    assert ls.followup_from_model(answer, "That sounds lovely.") is None
    assert ls.followup_from_model(answer, '"Where on Lake Tahoe did you fish?" I would also ask more.') == "Where on Lake Tahoe did you fish?"


def test_followup_inserted_after_its_question_and_capped():
    s = ls.new_session("u", "full")
    item = ls.add_followup(s, "roots.1", "Who else lived in the house?")
    assert item and s["queue"][1]["qid"] == "roots.1.f" and s["queue"][1]["kind"] == "followup"
    assert ls.add_followup(s, "roots.1", "Again?") is None
    s["followups"] = ls.MAX_FOLLOWUPS
    assert ls.add_followup(s, "roots.2", "More?") is None


def test_short_answers_make_no_followup_call():
    calls = []

    async def complete(system, user):
        calls.append(system)
        return "What?"

    assert run(ls.ask_followup("Yes, I did.", "q", complete)) is None
    assert calls == []
    assert not ls.substantial("no") and ls.substantial("We lived on Maple Street near the mill.")


def test_interview_card_is_pending_and_keeps_their_words():
    answer = "We lived on Maple Street. My uncle Ray built the porch."
    card = run(ls.draft_pending_card("u", answer, "Describe the home", fake_complete, source="interview", ref="liv_1", chapter="roots"))
    assert card["status"] == "pending" and card["source"] == "interview" and card["chapter"] == "roots"
    assert card["people"] == ["Ray"]  # Zelda was never said
    roles = ls.tag_card({"people": ["Dad", "foreman", "grandkids"]}, source="x")
    assert roles["people"] == ["Dad"]
    assert "Maple Street" in card["story"]


async def inventing_complete(system, user):
    return json.dumps({"title": "Paris", "era": "1970s", "people": [], "story": "I sailed to Paris and met the president of France at the Louvre."})


def test_model_invention_falls_back_to_their_words():
    answer = "We lived on Maple Street. My uncle Ray built the porch."
    card = run(ls.draft_pending_card("u", answer, "q", inventing_complete, source="interview"))
    assert card["story"] == answer


# ---------------------------------------------------------------- exported messages

WHATSAPP = """12/24/19, 7:02 PM - Messages and calls are end-to-end encrypted.
12/24/19, 7:03 PM - Pat Lee: Merry Christmas! Did the tamales turn out?
12/24/19, 7:05 PM - Sam Rivera: They did. I used my grandmother's recipe with the dried chiles from Hatch and we stayed up past midnight wrapping them
like we used to every year.
12/24/19, 7:06 PM - Sam Rivera: <Media omitted>
12/25/19, 9:15 AM - Pat Lee: ok
12/25/19, 9:16 AM - Sam Rivera: ok
"""


def test_whatsapp_export_owner_words_only():
    kind, msgs = ls.parse_messages("chat.txt", WHATSAPP.encode())
    assert kind == "whatsapp" and len(msgs) == 4
    assert msgs[1].text.endswith("like we used to every year.")
    assert {s["name"] for s in ls.senders(msgs)} == {"Pat Lee", "Sam Rivera"}
    rows = ls.passages_from_messages(msgs, "Sam Rivera")
    assert len(rows) == 1  # the "ok" day is too thin
    row = rows[0]
    assert row["day"] == "2019-12-24" and row["era"] == "2019" and row["people"] == ["Pat Lee"]
    assert "tamales turn out" not in row["transcript"]  # Pat's words are not Sam's memory
    assert "grandmother's recipe" in row["transcript"]


def test_whatsapp_day_first_and_bracket_format():
    text = "[25/12/2020, 21:41:05] Ana: I remember the snow in the village that winter and the bread my father baked at dawn.\n"
    _, msgs = ls.parse_messages("x.txt", text.encode())
    assert msgs[0].when.month == 12 and msgs[0].when.day == 25 and msgs[0].when.hour == 21


def test_messenger_json_fixes_mojibake_and_csv():
    data = {"messages": [
        {"sender_name": "Jos\u00c3\u00a9", "timestamp_ms": 1577836800000, "content": "Caf\u00c3\u00a9 con leche every morning at abuela's house, before school, with pan dulce on the table."},
        {"sender_name": "Ana", "timestamp_ms": 1577836900000},
    ]}
    kind, msgs = ls.parse_messages("message_1.json", json.dumps(data).encode())
    assert kind == "messenger" and len(msgs) == 1 and msgs[0].sender == "Jos\u00e9" and msgs[0].text.startswith("Caf\u00e9")
    csv_text = "Date,From,Body\n2018-06-01 10:00:00,Me,We drove the old Ford to Yellowstone and slept in the back when it rained all night\n2018-06-01 10:05:00,Kim,fun\n"
    kind, msgs = ls.parse_messages("sms.csv", csv_text.encode())
    assert kind == "csv" and msgs[0].when.year == 2018
    rows = ls.passages_from_messages(msgs, "me")
    assert rows[0]["people"] == ["Kim"] and "Yellowstone" in rows[0]["transcript"]


def test_message_passages_cap_richest_days_in_order():
    msgs = [ls.Msg(ls.datetime(2020, 1, d), "Me", ("word%d " % d) * (10 + d) + "garden tomatoes neighbors") for d in range(1, 21)]
    rows = ls.passages_from_messages(msgs, "Me", max_cards=5)
    assert [r["day"][-2:] for r in rows] == ["16", "17", "18", "19", "20"]


# ---------------------------------------------------------------- letters, documents, photos

def test_document_passages_and_letters_from_others():
    text = "\n\n".join(f"Paragraph {i}: the summer we painted the barn red and the cows watched from the fence." for i in range(80))
    rows = ls.passages_from_document(text, "Barn diary", max_cards=4)
    assert len(rows) == 4 and rows[0]["question"].startswith("From Barn diary (part 1)")
    assert all(len(r["transcript"]) <= 1400 for r in rows)
    letter = ls.passages_from_document("Dear one,\n\nI am so proud of the garden you planted for your mother.", "Letter", author="Grandma Rose")
    assert letter[0]["transcript"].startswith("A letter to me from Grandma Rose: ") and letter[0]["keepsake"]
    assert ls.passages_from_document("ok\n\nhi", "x") == []


def _jpeg_with_exif(description: str, taken: str) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (8, 8), "white")
    exif = Image.Exif()
    exif[0x010E] = description
    exif.get_ifd(0x8769)[0x9003] = taken
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_photo_caption_and_date_from_exif():
    pytest.importorskip("PIL")
    raw = _jpeg_with_exif("Dad and me at the county fair", "1987:08:14 15:30:00")
    found = ls.photo_details(raw)
    assert found == {"caption": "Dad and me at the county fair", "taken_at": "1987-08-14"}
    assert ls.photo_details(b"not an image") == {}
    assert ls.photo_transcript("Dad and me at the fair", "1987-08-14", "Tulsa") == "Dad and me at the fair Place: Tulsa. Photo taken 1987-08-14."


# ---------------------------------------------------------------- import job, review, grounding

def test_import_job_drafts_pending_cards_and_survives_a_down_model():
    db = FakeDb()
    job = {"import_id": "mimp_1", "user_id": "u"}
    run(db.memory_imports.insert_one({**job, "status": "drafting", "done": 0}))
    passages = ls.passages_from_messages(ls.parse_messages("c.txt", WHATSAPP.encode())[1], "Sam Rivera")

    async def down(system, user):
        raise RuntimeError("ollama down")

    run(ls.run_import(job, passages, source="messages", complete=down, store=db))
    card = db.memory_cards.docs[0]
    assert card["status"] == "pending" and card["source"] == "messages" and card["source_ref"] == "mimp_1"
    assert "Pat Lee" in card["people"] and card["era"] == "2019"
    letter = ls.passages_from_document("Dear one,\n\nI am so proud of the garden you planted for your mother.", "Letter", author="Grandma Rose")
    run(ls.run_import(job, letter, source="letter", complete=inventing_complete, store=db))
    kept = db.memory_cards.docs[-1]
    assert kept["keepsake"] and kept["story"].startswith("A letter to me from Grandma Rose: Dear one")
    assert db.memory_imports.docs[0]["status"] == "ready" and db.memory_imports.docs[0]["done"] == 1


def test_only_approved_cards_ground_and_approval_adds_vault_entry():
    db = FakeDb()
    answer = "My first car was a green 1968 Chevy Impala my uncle Ray sold me for 300 dollars."
    card = run(ls.draft_pending_card("u", answer, "What was your first car?", fake_complete, source="interview"))
    run(db.memory_cards.insert_one(card))
    pending = db.memory_cards.docs
    assert mc.select_cards(pending, "What was my first car?") == []  # pending never grounds
    approved = run(ls.approve_card(db, "u", card["card_id"]))
    assert approved["status"] == "approved" and approved["source"] == "interview"
    assert db.entries.docs[0]["source"] == "memory-card" and db.entries.docs[0]["visibility"] == "owner"
    hits = mc.select_cards(db.memory_cards.docs, "What was my first car?")
    assert hits and hits[0]["card_id"] == card["card_id"]
    assert "Impala" in mc.grounding_block(hits)
    # Approving twice does not duplicate the vault entry; another owner's id is refused.
    run(ls.approve_card(db, "u", card["card_id"]))
    assert len(db.entries.docs) == 1
    assert run(ls.approve_card(db, "someone-else", card["card_id"])) is None
    # Heirs never see owner-private cards.
    assert mc.visible_cards(db.memory_cards.docs, audience="heir") == []


def test_recall_embeds_each_card_once(monkeypatch):
    import local_inference

    calls = []

    async def fake_embed(texts, timeout=None):
        calls.append(len(texts))
        return [[1.0, float(i % 3), 0.5] for i in range(len(texts))]

    monkeypatch.setattr(local_inference, "ollama_embed_many", fake_embed)
    mc._VECTORS.clear()
    cards = [{"card_id": f"c{i}", "status": "approved", "title": f"Memory {i}", "story": f"story number {i} about the lake"} for i in range(60)]
    run(mc.recall_cards("When did we sail?", cards))
    run(mc.recall_cards("Where did we sail?", cards))
    assert calls == [61, 1]  # second turn embeds only the question
    cards[0] = {**cards[0], "story": "edited story about the mountain"}
    run(mc.recall_cards("Where did we sail?", cards))
    assert calls[-1] == 2


def test_claim_check_keeps_abbreviations_in_one_sentence():
    from grounding import split_sentences

    rows = split_sentences("My mother Irene was a nurse at St. Mary's. On a good day she sang. Dr. Olson delivered me.")
    assert rows == ["My mother Irene was a nurse at St. Mary's.", "On a good day she sang.", "Dr. Olson delivered me."]
    assert split_sentences("I paid 250 dollars. He was 5. OK.") == ["I paid 250 dollars.", "He was 5.", "OK."]
