"""Run the model benches across the hardware tiers and write one pass/fail matrix.

  python -m tier_suite                       # every tier's main model, every suite this machine can run
  python -m tier_suite --tiers small,cpu --fallbacks
  python -m tier_suite --tier auto --data %LOCALAPPDATA%\\HeirloomUnbound\\data   # this PC's tier (beta testers)
  python -m tier_suite --models gemma4:12b --suites core,tools --ollama http://127.0.0.1:11434
  python -m tier_suite --plan                # show what would run, run nothing

Suites (each is an existing bench, run in its own process with a time limit):
  core        model_bench: grounding, chat, tools, JSON, speed. Needs Ollama only.
  tools       model_bench_tools: the owner's local tool loop (weather, mail, calendar, files...). Ollama only.
  life_story  model_bench_life_story: interview, imports, approved-card recall. Needs the database.
  pipeline    model_bench_pipeline: the full eval-grounding run through a side API. Needs the database
              and an owner account on this box.

Models are never downloaded here: a tier whose model is not pulled is reported as "not pulled" with
the command to pull it. Cloud model tags are refused. The benches use made-up personas and clean up
their own rows; nothing about the owner is sent anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import model_tiers

HERE = Path(__file__).resolve().parent
SUITE_ORDER = ("core", "tools", "life_story", "pipeline")
DB_SUITES = {"life_story", "pipeline"}
TIMEOUT_S = {"core": 1800, "tools": 900, "life_story": 1200, "pipeline": 2400}

# Pass bars. They sit just under what the November 2026 tier winners scored (docs/MODEL-TIERS.md),
# so a regression in prompts, grounding or tools shows up as a FAIL on the tier it hurts.
CORE_MIN_QUALITY = 85.0
CORE_MIN_GROUNDING = 95.0
TOOLS_MIN_RIGHT = 9  # of 10
# eval-grounding misses already known and accepted for the small models (docs/MODEL-TIERS.md).
KNOWN_PIPELINE_MISSES = {"qwen3.5:4b": 1, "gemma4:e4b": 2, "gemma4:e2b": 2}


@dataclass
class Job:
    model: str
    num_ctx: int
    tiers: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    suite: str
    status: str  # pass | fail | skip | error
    detail: str = ""
    seconds: float = 0.0
    data: dict = field(default_factory=dict)


Runner = Callable[[list[str], dict, int], tuple[int, str]]


def _run(cmd: list[str], env: dict, timeout: int) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, cwd=str(HERE), env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, check=False)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return 124, out + f"\nTIMEOUT after {timeout}s"


# ---------------------------------------------------------------------- planning

def plan(tiers: str = "all", models: str = "", fallbacks: bool = False) -> list[Job]:
    """Tier names (or 'all' / 'auto') to a de-duplicated list of model runs."""
    jobs: dict[tuple[str, int], Job] = {}

    def add(model: str, ctx: int, tier: str, role: str) -> None:
        if model_tiers.is_cloud_tag(model):
            raise SystemExit(f"refusing cloud model {model}")
        job = jobs.setdefault((model, ctx), Job(model, ctx))
        label = tier if role in ("main", "custom") else f"{tier} ({role})"
        if label not in job.tiers:
            job.tiers.append(label)
        if role not in job.roles:
            job.roles.append(role)

    if models:
        for model in [m.strip() for m in models.split(",") if m.strip()]:
            add(model, 16384, "custom", "custom")
        return list(jobs.values())
    by_name = {t.name: t for t in model_tiers.TIERS}
    if tiers == "auto":
        choice = model_tiers.choose()
        wanted = [choice.tier]
    elif tiers == "all":
        wanted = list(by_name)
    else:
        wanted = [t.strip() for t in tiers.split(",") if t.strip()]
        unknown = [t for t in wanted if t not in by_name]
        if unknown:
            raise SystemExit(f"unknown tier(s) {unknown}; known: {', '.join(by_name)}")
    for name in wanted:
        tier = by_name[name]
        add(tier.model, tier.num_ctx, name, "main")
        if fallbacks and tier.fallback:
            add(tier.fallback, tier.num_ctx, name, "fallback")
    return list(jobs.values())


# ---------------------------------------------------------------------- environment

def load_local_box_env(data: Path) -> dict[str, str]:
    """heirloom.env from a local-box install (Install-HeirloomLocal.ps1)."""
    values: dict[str, str] = {}
    path = Path(data) / "heirloom.env"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def pulled_models(base: str) -> Optional[set[str]]:
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/api/tags", timeout=5) as resp:
            rows = json.loads(resp.read().decode()).get("models") or []
    except Exception:  # noqa: BLE001
        return None
    names = set()
    for row in rows:
        name = str(row.get("name") or "")
        names.add(name)
        if name.endswith(":latest"):
            names.add(name[: -len(":latest")])
    return names


def database_ready(env: dict) -> tuple[bool, str]:
    url = env.get("MONGO_URL") or ""
    if not url:
        return False, "no MONGO_URL"
    try:
        from pymongo import MongoClient
    except ImportError:
        return False, "pymongo not installed"
    try:
        client = MongoClient(url, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
        db = client[env.get("DB_NAME") or "heirloom"]
        owner = db.users.count_documents({"audience": "owner"}, limit=1) > 0
        client.close()
        return True, "owner" if owner else "no owner"
    except Exception as exc:  # noqa: BLE001
        return False, f"database not reachable ({type(exc).__name__})"


# ---------------------------------------------------------------------- judging

def _last_json_line(path: Path) -> dict:
    if not path.exists():
        return {}
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return json.loads(lines[-1]) if lines else {}


def judge_core(code: int, output: str, out_file: Path) -> Outcome:
    row = _last_json_line(out_file)
    if row.get("error") or not row.get("score"):
        return Outcome("core", "error", (row.get("error") or _tail(output))[:200])
    score = row["score"]
    decline = (row.get("grounding") or {}).get("decline") or {}
    ok = score["quality"] >= CORE_MIN_QUALITY and score["grounding"] >= CORE_MIN_GROUNDING
    detail = f"quality {score['quality']} (>= {CORE_MIN_QUALITY}), grounding {score['grounding']} (>= {CORE_MIN_GROUNDING})"
    if decline.get("of"):
        detail += f", declines untold {decline.get('right')}/{decline.get('of')}"
    speed = row.get("speed") or {}
    data = {"score": score, "tok_s": speed.get("tok_s"), "ttft_s": speed.get("ttft_s"), "load_s": row.get("load_s")}
    return Outcome("core", "pass" if ok else "fail", detail, data=data)


def judge_tools(code: int, output: str, out_file: Path) -> Outcome:
    row = _last_json_line(out_file)
    if not row.get("of"):
        return Outcome("tools", "error", _tail(output)[:200])
    ok = row["right"] >= TOOLS_MIN_RIGHT
    misses = [r["text"] for r in row.get("rows", []) if not r.get("ok")]
    detail = f"{row['right']}/{row['of']} (>= {TOOLS_MIN_RIGHT}), median {row.get('median_s')}s"
    if misses:
        detail += "; missed: " + "; ".join(m[:50] for m in misses[:3])
    return Outcome("tools", "pass" if ok else "fail", detail, data={"right": row["right"], "of": row["of"],
                                                                    "median_s": row.get("median_s")})


def judge_life_story(code: int, output: str, out_file: Path) -> Outcome:
    fails = [ln.strip() for ln in output.splitlines() if ln.strip().startswith("FAIL ")]
    timings = {}
    if out_file.exists():
        try:
            timings = (json.loads(out_file.read_text(encoding="utf-8")) or {}).get("timings") or {}
        except ValueError:
            timings = {}
    if code == 0 and re.search(r"^PASS\s*$", output, re.M):
        return Outcome("life_story", "pass", "interview, imports, recall and declines", data={"timings": timings})
    if "cleanup removed" not in output:
        return Outcome("life_story", "error", _tail(output)[:200])
    return Outcome("life_story", "fail", "; ".join(fails[:3])[:300] or _tail(output)[:200], data={"timings": timings})


def judge_pipeline(model: str) -> Callable[[int, str, Path], Outcome]:
    allowed = KNOWN_PIPELINE_MISSES.get(model, 0)

    def judge(code: int, output: str, out_file: Path) -> Outcome:
        bad = [ln.strip() for ln in output.splitlines() if ln.strip().startswith("BAD ")]
        if "Side API on" not in output or code == 124:
            return Outcome("pipeline", "error", _tail(output)[:200])
        ok = len(bad) <= allowed
        detail = f"{len(bad)} miss(es), {allowed} known for {model}"
        if bad:
            detail += "; " + "; ".join(b[:80] for b in bad[:3])
        return Outcome("pipeline", "pass" if ok else "fail", detail, data={"misses": len(bad), "allowed": allowed})

    return judge


def _tail(text: str, lines: int = 3) -> str:
    rows = [ln for ln in (text or "").splitlines() if ln.strip()]
    return " | ".join(rows[-lines:])


# ---------------------------------------------------------------------- running

def command(suite: str, job: Job, base: str, out_file: Path) -> list[str]:
    py = sys.executable
    if suite == "core":
        return [py, "-u", "-m", "model_bench", job.model, "--ollama", base, "--ctx", str(job.num_ctx), "--out", str(out_file)]
    if suite == "tools":
        return [py, "-u", "-m", "model_bench_tools", job.model, "--ollama", base, "--out", str(out_file)]
    if suite == "life_story":
        return [py, "-u", "-m", "model_bench_life_story", job.model, "--ollama", base, "--out", str(out_file)]
    if suite == "pipeline":
        return [py, "-u", "-m", "model_bench_pipeline", job.model, "--ollama", base]
    raise ValueError(suite)


def run(jobs: list[Job], suites: list[str], env: dict, out_dir: Path, *, runner: Runner = _run,
        pulled: Optional[set[str]] = None, db: tuple[bool, str] = (False, "not checked"),
        log: Callable[[str], None] = print) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = env.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
    results = []
    for job in jobs:
        row = {**asdict(job), "outcomes": []}
        results.append(row)
        log(f"== {job.model} (ctx {job.num_ctx}; tiers {', '.join(job.tiers)})")
        if pulled is not None and job.model not in pulled:
            row["outcomes"] = [asdict(Outcome(s, "skip", f"not pulled: ollama pull {job.model}")) for s in suites]
            log(f"   skip: not pulled (ollama pull {job.model})")
            continue
        for suite in suites:
            if suite in DB_SUITES and not db[0]:
                outcome = Outcome(suite, "skip", f"needs the database: {db[1]}")
            elif suite == "pipeline" and db[1] != "owner":
                outcome = Outcome(suite, "skip", "needs an owner account on this box")
            else:
                slug = re.sub(r"[^A-Za-z0-9]+", "_", job.model)
                out_file = out_dir / f"{suite}-{slug}-{job.num_ctx}.{'json' if suite == 'life_story' else 'jsonl'}"
                if out_file.exists():
                    out_file.unlink()
                began = time.perf_counter()
                code, output = runner(command(suite, job, base, out_file), env, TIMEOUT_S[suite])
                (out_dir / f"{suite}-{slug}-{job.num_ctx}.log").write_text(output, encoding="utf-8")
                judge = judge_pipeline(job.model) if suite == "pipeline" else {
                    "core": judge_core, "tools": judge_tools, "life_story": judge_life_story}[suite]
                try:
                    outcome = judge(code, output, out_file)
                except Exception as exc:  # noqa: BLE001
                    outcome = Outcome(suite, "error", f"could not read the result: {exc}"[:200])
                outcome.seconds = round(time.perf_counter() - began, 1)
            row["outcomes"].append(asdict(outcome))
            log(f"   {outcome.status.upper():5} {suite:10} {outcome.detail}")
    summary = {
        "at": datetime.now(timezone.utc).isoformat(),
        "ollama": base,
        "database": db[1] if db[0] else f"none ({db[1]})",
        "suites": suites,
        "results": results,
    }
    counts: dict[str, int] = {}
    for row in results:
        for o in row["outcomes"]:
            counts[o["status"]] = counts.get(o["status"], 0) + 1
    summary["counts"] = counts
    summary["ok"] = counts.get("fail", 0) == 0 and counts.get("error", 0) == 0 and counts.get("pass", 0) > 0
    (out_dir / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


def render_markdown(summary: dict) -> str:
    suites = summary["suites"]
    mark = {"pass": "PASS", "fail": "**FAIL**", "skip": "skip", "error": "**ERROR**"}
    lines = [
        "# Heirloom tier suite",
        "",
        f"Run {summary['at']} against Ollama {summary['ollama']}; database: {summary['database']}.",
        "",
        "| Model | ctx | Tiers | " + " | ".join(suites) + " |",
        "|---|---|---|" + "---|" * len(suites),
    ]
    for row in summary["results"]:
        by = {o["suite"]: o for o in row["outcomes"]}
        cells = [mark.get(by[s]["status"], by[s]["status"]) if s in by else "" for s in suites]
        tiers = ", ".join(row["tiers"])
        lines.append(f"| {row['model']} | {row['num_ctx']} | {tiers} | " + " | ".join(cells) + " |")
    lines += ["", "## Details", ""]
    for row in summary["results"]:
        for o in row["outcomes"]:
            secs = f" ({o['seconds']} s)" if o.get("seconds") else ""
            lines.append(f"- **{row['model']}** {o['suite']}: {o['status']}{secs}. {o['detail']}")
    verdict = "All suites that ran passed." if summary["ok"] else "Something failed or nothing ran; see the details and logs."
    lines += ["", f"Counts: {summary['counts']}. {verdict}", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="tier_suite", description=__doc__.split("\n\n")[0])
    ap.add_argument("--tiers", "--tier", default="all", help="all, auto, or a comma list of tier names")
    ap.add_argument("--models", default="", help="comma list of model tags instead of tiers")
    ap.add_argument("--fallbacks", action="store_true", help="also run each tier's fallback model")
    ap.add_argument("--suites", default=",".join(SUITE_ORDER))
    ap.add_argument("--ollama", default="")
    ap.add_argument("--data", default="", help="a local-box data folder (reads heirloom.env)")
    ap.add_argument("--out", default="", help="results folder (default tier-suite-<time>)")
    ap.add_argument("--plan", action="store_true", help="print the plan and exit")
    args = ap.parse_args(argv)

    suites = [s.strip() for s in args.suites.split(",") if s.strip()]
    bad = [s for s in suites if s not in SUITE_ORDER]
    if bad:
        print(f"unknown suite(s) {bad}; known: {', '.join(SUITE_ORDER)}")
        return 2
    env = dict(os.environ)
    if args.data:
        env.update(load_local_box_env(Path(args.data)))
    if args.ollama:
        env["OLLAMA_BASE_URL"] = args.ollama
    env.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    env["PYTHONIOENCODING"] = "utf-8"
    tiers = args.tiers
    if tiers == "auto" and env.get("HEIRLOOM_MODEL_TIER") in {t.name for t in model_tiers.TIERS}:
        tiers = env["HEIRLOOM_MODEL_TIER"]  # the tier this local box was installed with
    jobs = plan(tiers, args.models, args.fallbacks)
    if args.plan:
        for job in jobs:
            print(f"{job.model:22} ctx {job.num_ctx:6}  tiers {', '.join(job.tiers)}")
        print(f"suites: {', '.join(suites)}")
        return 0
    pulled = pulled_models(env["OLLAMA_BASE_URL"])
    if pulled is None:
        print(f"Ollama is not answering at {env['OLLAMA_BASE_URL']}.")
        return 2
    db = database_ready(env) if DB_SUITES & set(suites) else (False, "not needed")
    out_dir = Path(args.out or f"tier-suite-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    summary = run(jobs, suites, env, out_dir, pulled=pulled, db=db)
    print(f"\nReport: {out_dir / 'report.md'}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
