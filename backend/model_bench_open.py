"""Open-ended answer quality for the tier bench, graded by local judge models.

  python -m model_bench_open answer MODEL [MODEL ...] --ollama URL --out answers.jsonl
  python -m model_bench_open judge answers.jsonl --judges qwen3.8:27b,gemma4:31b --ollama URL --out grades.jsonl

The fixed checks in model_bench cannot tell a flat answer from a good one. Here
each model answers the same everyday requests a buyer would make, then three
local judges from different families grade every answer 1-10 without seeing
which model wrote it. A model never grades its own answers. Local Ollama only.
"""
from __future__ import annotations

import json
import random
import re
import statistics
import sys
from collections import defaultdict

from model_bench import ASSISTANT_SYSTEM, Bench, _post, _text, _unload
from model_tiers import is_cloud_tag

OPEN_PROMPTS = [
    "My granddaughter is starting college next month. Write her a heartfelt card message, about 80 words.",
    "Explain the difference between a will and a living trust in plain language.",
    "I've been feeling lonely since my wife passed last spring. Any gentle suggestions?",
    "Help me write an email to my landlord about a leaking kitchen faucet that's been ignored for two weeks. Firm but polite.",
    "What questions should I ask my doctor about starting a new blood pressure medication?",
    "Plan a simple 3-day visit to Yellowstone with grandkids aged 6 and 9.",
    "My iPhone keeps saying storage is full. Walk me through fixing it, step by step.",
    "Give me a budget weeknight dinner plan for 5 nights for two people, with one combined shopping list.",
]

JUDGE_SYSTEM = """You grade one answer from a personal AI assistant used by ordinary families, many of them older adults.
Score 1-10 for overall quality: helpful and complete for the request, factually correct and safe, clear and well organized,
warm and appropriate in tone, and not padded. 10 = excellent, 7 = good with small gaps, 4 = weak, 1 = wrong or useless.
Return only JSON: {"score": <1-10>, "reason": "<one short sentence>"}"""


def answer(base: str, models: list[str], out: str) -> None:
    for model in models:
        if is_cloud_tag(model):
            continue
        bench = Bench(base, model, 16384)
        for prompt in OPEN_PROMPTS:
            try:
                data, secs = bench.chat([{"role": "system", "content": ASSISTANT_SYSTEM}, {"role": "user", "content": prompt}],
                                        num_predict=900, temperature=0.3)
                text = _text(data)
            except Exception as exc:  # noqa: BLE001
                text, secs = f"ERROR {exc}", 0.0
            with open(out, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"model": model, "prompt": prompt, "answer": text, "seconds": round(secs, 2)}) + "\n")
        _unload(base, model)
        print(f"answered {model}", flush=True)


def _family(tag: str) -> str:
    return re.split(r"[:.\d]", tag.lower(), maxsplit=1)[0]


def judge(base: str, answers_file: str, judges: list[str], out: str) -> None:
    rows = [json.loads(line) for line in open(answers_file, encoding="utf-8") if line.strip()]
    random.Random(7).shuffle(rows)
    for judge_model in judges:
        bench = Bench(base, judge_model, 16384)
        for row in rows:
            if _family(row["model"]) == _family(judge_model):
                continue  # no grading its own family
            prompt = f"REQUEST:\n{row['prompt']}\n\nANSWER:\n{row['answer'][:6000]}"
            try:
                data, _ = bench.chat([{"role": "system", "content": JUDGE_SYSTEM}, {"role": "user", "content": prompt}],
                                     fmt={"type": "object", "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}},
                                          "required": ["score", "reason"]}, num_predict=120, temperature=0.0)
                graded = json.loads(_text(data))
                value = max(1, min(10, int(graded.get("score"))))
            except Exception as exc:  # noqa: BLE001
                value, graded = None, {"reason": f"ERROR {exc}"}
            with open(out, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"judge": judge_model, "model": row["model"], "prompt": row["prompt"][:60],
                                         "score": value, "reason": str(graded.get("reason", ""))[:200]}) + "\n")
        _unload(base, judge_model)
        print(f"judged with {judge_model}", flush=True)


def summary(grades_file: str) -> dict[str, float]:
    """Mean grade per model after removing each judge's own leniency (judge mean centered)."""
    rows = [json.loads(line) for line in open(grades_file, encoding="utf-8") if line.strip()]
    rows = [row for row in rows if row.get("score") is not None]
    if not rows:
        return {}
    overall = statistics.mean(float(row["score"]) for row in rows)
    by_judge: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_judge[row["judge"]].append(float(row["score"]))
    shift = {judge: overall - statistics.mean(values) for judge, values in by_judge.items()}
    per: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        per[row["model"]].append(float(row["score"]) + shift[row["judge"]])
    return {model: round(statistics.mean(values), 2) for model, values in sorted(per.items(), key=lambda kv: -statistics.mean(kv[1]))}


def main(argv: list[str]) -> int:
    args = list(argv)
    if not args:
        print(__doc__)
        return 2
    command = args.pop(0)
    base, out, judges, items = "http://127.0.0.1:11434", "", [], []
    while args:
        item = args.pop(0)
        if item == "--ollama" and args:
            base = args.pop(0)
        elif item == "--out" and args:
            out = args.pop(0)
        elif item == "--judges" and args:
            judges = [j for j in args.pop(0).split(",") if j]
        else:
            items.append(item)
    if command == "answer":
        answer(base, items, out)
    elif command == "judge":
        judge(base, items[0], judges, out)
    elif command == "summary":
        print(json.dumps(summary(items[0]), indent=2))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
