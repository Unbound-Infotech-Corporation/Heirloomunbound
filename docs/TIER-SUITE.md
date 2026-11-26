# Tier test suite

One command runs every model bench across the hardware tiers and writes a pass/fail matrix.

    cd backend
    python -m tier_suite --plan                                   # what would run
    python -m tier_suite                                          # all tiers, all suites this machine can run
    python -m tier_suite --tiers small,cpu --fallbacks            # chosen tiers plus their fallback models
    python -m tier_suite --models gemma4:12b --suites core,tools  # any local model tag
    python -m tier_suite --tier auto --data <local-box data dir>  # this PC's installed tier (what testers run)

On a Twin Box, run it in the side container so the live API is untouched:

    ~/hlbench/run.sh python -u -m tier_suite --tiers large --fallbacks --ollama http://ollama:11434 --out /out/ts

## Suites

| Suite | Bench | Needs | Pass bar |
|---|---|---|---|
| core | `model_bench` (grounding, chat, tools, JSON, speed) | Ollama | quality >= 85 and grounding >= 95 |
| tools | `model_bench_tools` (10 owner requests with canned tool data) | Ollama | 9 of 10 |
| life_story | `model_bench_life_story` (interview, imports, approved-card recall, declines) | database | every check, and cleanup leaves 0 rows |
| pipeline | `model_bench_pipeline` (full eval-grounding through a side API) | database + owner | no misses beyond the ones already known for that model |

The bars sit just under what the November 2026 tier winners scored (`docs/MODEL-TIERS.md`).
Known pipeline misses: qwen3.5:4b 1, gemma4:e4b 2, gemma4:e2b 2 (`KNOWN_PIPELINE_MISSES`).

- Each bench runs in its own process with a time limit; a crash or timeout is an **ERROR**, not a pass.
- A model that is not pulled is **skipped** with the `ollama pull` command. The suite never downloads.
- Suites that need the database are skipped when it is not reachable; `pipeline` also needs an owner account.
- Cloud model tags are refused.
- Output folder: `results.json`, `report.md` (the matrix), and one log per bench. Exit code 0 only when
  something ran and nothing failed.
- The benches use made-up personas and canned tool data, and delete the rows they make.

`tests/test_tier_suite.py` covers planning, judging, skips, errors and the report with a fake runner,
so CI checks the suite itself without a GPU.

## Beta testers

`Heirloom-Selftest.ps1` (installed next to Start/Stop) runs `--tier auto` with core, tools and life_story
against the tester's own install and zips the report, hardware plan and install log. It never includes
`heirloom.env`, the database, the vault or the API logs. See `docs/BETA-PLAN.md`.
