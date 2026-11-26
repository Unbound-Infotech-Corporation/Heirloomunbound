"""Live check of the life-story interview and imports against a local model.

Runs the real router functions against the box database as a throwaway user
(``bench_life_<hex>``), with a made-up persona, then deletes every row it made.

  python -m model_bench_life_story [MODEL] [--ollama URL] [--out FILE]

What it checks:
- interview answers become pending cards that keep the persona's words
- follow-up questions only use names and things the persona said
- a chat export, a letter, and a captioned photo become pending cards
- pending cards never answer; approved cards do; untold things are declined
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import time
import uuid

PERSONA = {
    "roots.1": "I was born in 1951 in Duluth, Minnesota. My mother Irene, my father Walter and my little brother Pete lived in a narrow house on Fourth Street near the ore docks.",
    "roots.2": "The kitchen. My mother baked rye bread every Saturday and the windows fogged up so we drew boats on the glass.",
    "family.1": "My mother Irene was a nurse at St. Mary's. On a good day she sang Patsy Cline while she ironed and let us stay up for the late movie.",
    "school.1": "Mrs. Halvorsen taught eighth grade science. She let me keep a garter snake named Rudy in a tank by the window.",
    "young.3": "My first car was a 1963 Ford Falcon, pale blue, that I bought for 250 dollars from my uncle Leo in 1969.",
    "work.1": "I worked thirty-one years as a lineman for the power company. I got into it because my father Walter knew the foreman.",
}
CHAT = """6/14/14, 6:02 PM - Pete: Did you get the boat in the water?
6/14/14, 6:10 PM - Dale: Finally. Took the old Lund out to Pike Lake with the grandkids and Emma caught her first walleye, nineteen inches, she would not let anyone else hold it.
6/14/14, 6:11 PM - Pete: ha good for her
"""
LETTER = "Dear Dale,\n\nI am proud of you for finishing the apprenticeship. Your grandfather would have been proud too. Remember to call your mother on Sundays.\n\nLove, Aunt Ruth"
RECALL = [
    ("What was my first car?", ("falcon",)),
    ("Where did I grow up?", ("duluth",)),
    ("What did my mother do for work?", ("nurse",)),
    ("Who caught a walleye at Pike Lake?", ("emma",)),
    ("What did Aunt Ruth write to me about?", ("apprentice", "proud")),
]
UNTOLD = ["What was my first dog's name?", "Where did I go to college?", "What was my wedding like?"]


def _jpeg(caption: str) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (16, 16), "skyblue")
    exif = Image.Exif()
    exif[0x010E] = caption
    exif.get_ifd(0x8769)[0x9003] = "1978:07:04 12:00:00"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


async def main(model: str, out_path: str) -> int:
    from fastapi import UploadFile

    import life_story as ls
    import memory_cards as mc
    import routers.life_story as rl
    from deps import db
    from grounding import verify_reply

    uid = f"bench_life_{uuid.uuid4().hex[:8]}"
    user = {"user_id": uid, "audience": "owner"}
    report: dict = {"model": model, "checks": [], "timings": {}}
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        report["checks"].append({"name": name, "pass": passed, "detail": detail})
        print(("PASS " if passed else "FAIL ") + name + (f"  [{detail}]" if detail and not passed else ""), flush=True)

    try:
        t0 = time.perf_counter()
        await rl.start_interview(rl.StartReq(length="full"), user)
        turn_times, followups = [], []
        for qid, answer in PERSONA.items():
            t = time.perf_counter()
            res = await rl.answer(rl.AnswerReq(qid=qid, transcript=answer), user)
            turn_times.append(time.perf_counter() - t)
            card = res["card"]
            check(f"interview card {qid} pending, in their words", bool(card) and card["status"] == "pending"
                  and mc._story_stays_in_their_words(card["story"], answer), json.dumps(card, default=str)[:300] if card else "none")
            if res.get("followup"):
                q = res["followup"]["question"]
                followups.append(q)
                check(f"follow-up uses their words: {q[:70]}", ls.followup_from_model(answer, q) == q)
        res = await rl.answer(rl.AnswerReq(qid="roots.3", transcript="Not much."), user)
        check("short answer makes no card", res["card"] is None)
        report["followups"] = followups
        report["timings"]["interview_turn_median_s"] = sorted(turn_times)[len(turn_times) // 2]
        report["timings"]["interview_turn_max_s"] = max(turn_times)

        prev = await rl.preview_messages(UploadFile(io.BytesIO(CHAT.encode()), filename="WhatsApp Chat with Pete.txt"), user)
        check("chat preview lists senders", {s["name"] for s in prev["senders"]} == {"Pete", "Dale"})
        await rl.import_messages(UploadFile(io.BytesIO(CHAT.encode()), filename="WhatsApp Chat with Pete.txt"), "Dale", 25, user)
        await rl.import_document(UploadFile(io.BytesIO(LETTER.encode()), filename="ruth.txt"), "Aunt Ruth", "Letter from Aunt Ruth", user)
        await asyncio.gather(*list(rl._jobs))
        jobs = (await rl.list_imports(user))["imports"]
        check("imports finished", jobs and all(j["status"] == "ready" for j in jobs), json.dumps(jobs, default=str)[:300])
        cap = "Dad and me on the dock at Park Point on the Fourth of July with sparklers"
        ph = await rl.import_photo(UploadFile(io.BytesIO(_jpeg(cap)), filename="dock.jpg"), "", "", "", user)
        check("photo caption read from the file", bool(ph.get("card")) and str(ph["card"].get("era") or "").startswith("1978"), json.dumps(ph, default=str)[:300])

        listed = await rl.list_cards("pending", "", user)
        pending = listed["cards"]
        sources = {c.get("source") for c in pending}
        check("all sources became pending cards", {"interview", "messages", "letter", "photo"} <= sources, str(sources))
        chat_card = next((c for c in pending if c.get("source") == "messages"), {})
        check("chat card keeps only the owner's words", "boat in the water" not in chat_card.get("story", "") and "walleye" in chat_card.get("story", "").lower())

        cards = await db.memory_cards.find({"user_id": uid}, {"_id": 0}).to_list(length=200)
        none = await mc.answer_grounded("What was my first car?", cards, rl._complete, verify=verify_reply)
        check("pending cards do not answer", none["reply"] == mc.NO_MEMORY_YET, none["reply"])

        await rl.approve_cards(rl.ApproveReq(card_ids=[c["card_id"] for c in pending]), user)
        approved = await db.memory_cards.find({"user_id": uid, "status": "approved"}, {"_id": 0}).to_list(length=200)
        check("approved and added to the vault", len(approved) == len(pending)
              and await db.entries.count_documents({"user_id": uid, "source": "memory-card"}) == len(pending))

        ask_times = []
        for question, needles in RECALL:
            t = time.perf_counter()
            got = await mc.answer_grounded(question, approved, rl._complete, verify=verify_reply)
            ask_times.append(time.perf_counter() - t)
            reply = got["reply"].lower()
            check(f"recall: {question}", any(n in reply for n in needles) and bool(got["why"]), got["reply"][:160])
        for question in UNTOLD:
            t = time.perf_counter()
            got = await mc.answer_grounded(question, approved, rl._complete, verify=verify_reply)
            ask_times.append(time.perf_counter() - t)
            check(f"declines untold: {question}", got["reply"] == mc.NO_MEMORY_YET, got["reply"][:160])
        report["timings"]["ask_median_s"] = sorted(ask_times)[len(ask_times) // 2]
        report["timings"]["total_s"] = time.perf_counter() - t0
        report["cards"] = [{k: c.get(k) for k in ("source", "title", "era", "people", "story")} for c in approved]
    finally:
        removed = {}
        for name in ("memory_cards", "entries", "memory_imports", "life_interviews", "photos", "daily_prompts"):
            result = await getattr(db, name).delete_many({"user_id": uid})
            removed[name] = result.deleted_count
        left = sum([await getattr(db, n).count_documents({"user_id": uid}) for n in removed])
        report["cleanup"] = removed
        print(f"cleanup removed {removed}; left {left}", flush=True)
        ok = ok and left == 0
    print(json.dumps(report["timings"]), flush=True)
    print("PASS" if ok else "FAIL", flush=True)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
    return 0 if ok else 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    model, out = "", ""
    while argv:
        item = argv.pop(0)
        if item == "--ollama" and argv:
            os.environ["OLLAMA_BASE_URL"] = argv.pop(0)
        elif item == "--out" and argv:
            out = argv.pop(0)
        else:
            model = item
    if model:
        os.environ["OLLAMA_TWIN_MODEL"] = model
    sys.exit(asyncio.run(main(model or os.environ.get("OLLAMA_TWIN_MODEL", ""), out)))
