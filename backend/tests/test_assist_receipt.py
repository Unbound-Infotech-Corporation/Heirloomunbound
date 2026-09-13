"""Assist action receipts — shape, status, plan chip, Twin-only omit."""
from __future__ import annotations

from pathlib import Path

from assist_receipt import (
    STATUS_DID,
    STATUS_FAILED,
    STATUS_WAITING_CONFIRM,
    build_assist_receipt,
    receipt_for_role,
    step_from_trace,
)


def _row(name, *, ok=True, needs_confirm=False, summary="", uid="t1"):
    return {
        "id": uid,
        "name": name,
        "args": {},
        "ui": {"ok": ok, "needs_confirm": needs_confirm},
        "summary": summary,
        "ts": "2026-01-01T00:00:00+00:00",
    }


def test_receipt_omitted_for_twin_role():
    trace = [_row("open_on_pc", summary="Opened Chrome")]
    assert receipt_for_role("twin", trace, reply="Opened it.") is None
    assert build_assist_receipt(trace, reply="Opened it.", include=False) is None


def test_assist_without_tools_still_receipts():
    rec = receipt_for_role("assistant", [], reply="I can do that after you Confirm.")
    assert rec is not None
    assert rec["status"] == STATUS_DID
    assert rec["steps"] == []
    assert rec["plan"] is None
    assert rec["summary"].startswith("I can do that")


def test_assist_empty_reply_no_tools_is_honest():
    rec = build_assist_receipt([], reply="  ")
    assert rec["summary"] == "Answered. No PC action this turn."
    assert rec["status"] == STATUS_DID


def test_did_single_step_has_no_plan():
    rec = build_assist_receipt(
        [_row("open_on_pc", summary="Opened Chrome")],
        reply="Opened Chrome.",
    )
    assert rec["status"] == STATUS_DID
    assert rec["plan"] is None
    assert rec["steps"][0]["name"] == "open_on_pc"
    assert rec["steps"][0]["label"] == "Open on this PC"
    assert rec["steps"][0]["ok"] is True
    assert rec["summary"] == "Opened Chrome"


def test_multi_step_emits_plan_and_did():
    rec = build_assist_receipt(
        [
            _row("open_on_pc", summary="Opened Chrome", uid="a"),
            _row("see_screen", summary="Looked at the screen", uid="b"),
        ],
        reply="Done.",
    )
    assert rec["status"] == STATUS_DID
    assert rec["plan"] == ["Open on this PC", "See the screen"]
    assert rec["summary"] == "Opened Chrome; Looked at the screen"
    assert [s["name"] for s in rec["steps"]] == ["open_on_pc", "see_screen"]


def test_failed_step_sets_failed_status():
    rec = build_assist_receipt(
        [_row("run_command", ok=False, summary="Command failed: access denied")],
        reply="That didn't work.",
    )
    assert rec["status"] == STATUS_FAILED
    assert rec["steps"][0]["ok"] is False
    assert rec["plan"] is None
    assert "access denied" in rec["summary"]


def test_confirm_sets_waiting_and_plan():
    rec = build_assist_receipt(
        [_row("power_action", ok=False, needs_confirm=True, summary="Shutdown needs Confirm")],
        reply="I'll wait.",
    )
    assert rec["status"] == STATUS_WAITING_CONFIRM
    assert rec["steps"][0]["needs_confirm"] is True
    assert rec["steps"][0]["ok"] is False
    assert rec["plan"] == ["Power control"]
    assert rec["summary"].startswith("Waiting for Confirm")


def test_confirm_beats_failed_when_mixed():
    rec = build_assist_receipt(
        [
            _row("open_on_pc", ok=True, summary="Opened Chrome", uid="a"),
            _row("run_command", ok=False, needs_confirm=True, summary="Needs Confirm", uid="b"),
        ],
        reply="Waiting.",
    )
    assert rec["status"] == STATUS_WAITING_CONFIRM
    assert rec["plan"] == ["Open on this PC", "Run a command"]


def test_missing_ui_ok_defaults_success():
    step = step_from_trace({"id": "x", "name": "set_volume", "ui": {}})
    assert step["ok"] is True
    assert step["needs_confirm"] is False
    assert step["label"] == "Set volume"


def test_receipt_shape_keys():
    rec = build_assist_receipt([_row("clipboard", summary="Copied")], reply="Copied.")
    assert set(rec) == {"status", "summary", "steps", "plan"}
    assert set(rec["steps"][0]) == {"id", "name", "label", "ok", "needs_confirm", "summary"}


def test_owner_response_fields_include_receipt_only_on_do():
    from owner_rail import OwnerTurnResult, owner_response_fields

    twin_only = OwnerTurnResult(reply="A story.", rail="twin", rail_chip="As you", rail_legs=["twin"])
    assert "receipt" not in owner_response_fields(twin_only)

    assist = OwnerTurnResult(
        reply="Opened Chrome.",
        rail="assist",
        rail_chip="Do",
        rail_legs=["assist"],
        assist_reply="Opened Chrome.",
        receipt=build_assist_receipt([_row("open_on_pc", summary="Opened Chrome")], reply="Opened Chrome."),
    )
    fields = owner_response_fields(assist)
    assert fields["receipt"]["status"] == STATUS_DID
    assert fields["assist_reply"] == "Opened Chrome."
    assert "twin_reply" not in fields

    both = OwnerTurnResult(
        reply="Filed.\n\nOpened it.",
        rail="both",
        rail_chip="Do + As you",
        rail_legs=["twin", "assist"],
        twin_reply="Filed.",
        assist_reply="Opened it.",
        receipt=build_assist_receipt([_row("open_on_pc", summary="Opened it")], reply="Opened it."),
    )
    both_fields = owner_response_fields(both)
    assert both_fields["twin_reply"] == "Filed."
    assert both_fields["assist_reply"] == "Opened it."
    assert both_fields["receipt"]["steps"][0]["name"] == "open_on_pc"


def test_owner_page_renders_receipt_and_leg_split():
    src = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "Owner.jsx"
    ).read_text(encoding="utf-8")
    assert "AssistReceipt" in src
    assert "owner-twin-leg" in src
    assert "owner-assist-leg" in src
    assert "shouldShowReceipt" in src


def test_web_twin_stays_without_assist_receipt():
    src = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "Twin.jsx"
    ).read_text(encoding="utf-8")
    assert "AssistReceipt" not in src
    assert "waiting_confirm" not in src


def test_heir_portal_has_no_receipt_surface():
    src = (
        Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages" / "HeirPortal.jsx"
    ).read_text(encoding="utf-8")
    assert "AssistReceipt" not in src
    assert "receipt" not in src
