"""tier_suite: planning, judging and the report, with a fake runner (no Ollama, no database)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import model_tiers  # noqa: E402
import tier_suite as ts  # noqa: E402


def test_all_tiers_plan_each_main_model_once_per_context():
    jobs = ts.plan("all")
    keys = [(j.model, j.num_ctx) for j in jobs]
    assert len(keys) == len(set(keys))
    for tier in model_tiers.TIERS:
        assert any(j.model == tier.model and j.num_ctx == tier.num_ctx and tier.name in j.tiers for j in jobs)
    twelve = next(j for j in jobs if j.model == "gemma4:12b")
    assert twelve.tiers == ["large", "medium"]


def test_fallbacks_are_labelled_and_unknown_tiers_refused():
    jobs = ts.plan("small", fallbacks=True)
    assert [(j.model, j.tiers) for j in jobs] == [("qwen3.5:4b", ["small"]), ("gemma4:e2b", ["small (fallback)"])]
    with pytest.raises(SystemExit):
        ts.plan("huge")


def test_cloud_models_are_refused():
    with pytest.raises(SystemExit):
        ts.plan(models="gpt-4o,gemma4:12b")


def test_auto_uses_this_machines_tier(monkeypatch):
    monkeypatch.setattr(model_tiers, "detect_hardware",
                        lambda: model_tiers.Hardware(vendor="nvidia", gpu="RTX 3060", vram_mib=12288, ram_mib=32768))
    monkeypatch.delenv("HEIRLOOM_TWIN_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_TWIN_MODEL", raising=False)
    jobs = ts.plan("auto")
    assert len(jobs) == 1 and jobs[0].model == model_tiers.choose().model


def _fake_runner(results: dict):
    """results[(suite, model)] -> (exit code, stdout, file payload)."""
    calls = []

    def runner(cmd, env, timeout):
        module = cmd[cmd.index("-m") + 1]
        suite = {"model_bench": "core", "model_bench_tools": "tools", "model_bench_life_story": "life_story",
                 "model_bench_pipeline": "pipeline"}[module]
        model = cmd[cmd.index("-m") + 2]
        calls.append((suite, model, timeout))
        code, out, payload = results[(suite, model)]
        if "--out" in cmd and payload is not None:
            Path(cmd[cmd.index("--out") + 1]).write_text(payload, encoding="utf-8")
        return code, out

    runner.calls = calls
    return runner


def _core(quality, grounding):
    return json.dumps({"model": "m", "score": {"quality": quality, "grounding": grounding},
                       "grounding": {"decline": {"right": 8, "of": 8}}, "speed": {"tok_s": 99.0, "ttft_s": 0.1}}) + "\n"


def _tools(right):
    rows = [{"text": f"case {i}", "ok": i < right} for i in range(10)]
    return json.dumps({"model": "m", "right": right, "of": 10, "median_s": 0.5, "rows": rows}) + "\n"


def test_run_writes_matrix_and_fails_on_a_regression(tmp_path):
    runner = _fake_runner({
        ("core", "gemma4:12b"): (0, "", _core(92.0, 100.0)),
        ("tools", "gemma4:12b"): (0, "", _tools(10)),
        ("life_story", "gemma4:12b"): (0, "cleanup removed {}; left 0\nPASS\n", json.dumps({"timings": {"ask_median_s": 0.6}})),
        ("pipeline", "gemma4:12b"): (0, "Side API on :8002\n  ok  1.0s  q -> a\n", None),
        ("core", "qwen3.5:4b"): (0, "", _core(80.0, 100.0)),  # regression: under the quality bar
        ("tools", "qwen3.5:4b"): (0, "", _tools(8)),
        ("life_story", "qwen3.5:4b"): (1, "  FAIL recall: What was my first car?\ncleanup removed {}; left 0\nFAIL\n", None),
        ("pipeline", "qwen3.5:4b"): (1, "Side API on :8002\n  BAD   2.0s  How do I clean a trout? -> declined\n", None),
    })
    jobs = ts.plan(models="gemma4:12b,qwen3.5:4b")
    summary = ts.run(jobs, list(ts.SUITE_ORDER), {"OLLAMA_BASE_URL": "http://x"}, tmp_path, runner=runner,
                     pulled={"gemma4:12b", "qwen3.5:4b"}, db=(True, "owner"), log=lambda _: None)
    status = {(r["model"], o["suite"]): o["status"] for r in summary["results"] for o in r["outcomes"]}
    assert all(status[("gemma4:12b", s)] == "pass" for s in ts.SUITE_ORDER)
    assert status[("qwen3.5:4b", "core")] == "fail"
    assert status[("qwen3.5:4b", "tools")] == "fail"
    assert status[("qwen3.5:4b", "life_story")] == "fail"
    assert status[("qwen3.5:4b", "pipeline")] == "pass"  # one trout miss is known and accepted for qwen3.5:4b
    assert summary["ok"] is False
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| gemma4:12b | 16384 | custom | PASS | PASS | PASS | PASS |" in report
    assert "**FAIL**" in report and "first car" in report
    assert json.loads((tmp_path / "results.json").read_text())["counts"] == {"pass": 5, "fail": 3}
    assert {t for _, _, t in runner.calls} == set(ts.TIMEOUT_S.values())


def test_missing_models_and_database_are_skipped_not_failed(tmp_path):
    runner = _fake_runner({
        ("core", "gemma4:e4b"): (0, "", _core(92.6, 100.0)),
        ("tools", "gemma4:e4b"): (0, "", _tools(10)),
    })
    jobs = ts.plan("cpu", fallbacks=True)
    summary = ts.run(jobs, list(ts.SUITE_ORDER), {}, tmp_path, runner=runner, pulled={"gemma4:e4b"},
                     db=(False, "database not reachable"), log=lambda _: None)
    by = {r["model"]: {o["suite"]: o for o in r["outcomes"]} for r in summary["results"]}
    assert by["gemma4:e4b"]["core"]["status"] == "pass"
    assert by["gemma4:e4b"]["life_story"]["status"] == "skip"
    assert "ollama pull gemma4:e2b" in by["gemma4:e2b"]["core"]["detail"]
    assert summary["ok"] is True
    assert len(runner.calls) == 2


def test_pipeline_needs_an_owner_and_crashes_are_errors(tmp_path):
    runner = _fake_runner({
        ("core", "gemma4:26b"): (1, "Traceback: boom", json.dumps({"model": "gemma4:26b", "error": "connection refused"}) + "\n"),
        ("life_story", "gemma4:26b"): (1, "Traceback (most recent call last):\nKeyError: x\n", None),
    })
    summary = ts.run(ts.plan("xl"), ["core", "life_story", "pipeline"], {}, tmp_path, runner=runner,
                     pulled={"gemma4:26b"}, db=(True, "no owner"), log=lambda _: None)
    outs = {o["suite"]: o for o in summary["results"][0]["outcomes"]}
    assert outs["core"]["status"] == "error" and "connection refused" in outs["core"]["detail"]
    assert outs["life_story"]["status"] == "error"
    assert outs["pipeline"]["status"] == "skip"
    assert summary["ok"] is False


def test_local_box_env_is_read(tmp_path):
    (tmp_path / "heirloom.env").write_text("# c\nMONGO_URL=mongodb://127.0.0.1:27181\nOLLAMA_BASE_URL=http://127.0.0.1:11434\n",
                                           encoding="utf-8")
    env = ts.load_local_box_env(tmp_path)
    assert env == {"MONGO_URL": "mongodb://127.0.0.1:27181", "OLLAMA_BASE_URL": "http://127.0.0.1:11434"}


def test_commands_use_the_tier_context_and_this_python():
    job = ts.Job("qwen3.5:4b", 8192, ["compact"])
    cmd = ts.command("core", job, "http://o", Path("x.jsonl"))
    assert cmd[0] == sys.executable and cmd[cmd.index("--ctx") + 1] == "8192"
    assert "--out" not in ts.command("pipeline", job, "http://o", Path("x"))
