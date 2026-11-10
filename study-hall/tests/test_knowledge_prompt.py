"""The twin only sees a lesson after it is filed, and only when the question overlaps it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from study_knowledge import attach_study_to_prompt, study_prompt_block  # noqa: E402


def _write(path: Path, summary: str, *, confidence: float = 0.8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "lessons": [{
            "lesson_id": "les_test",
            "summary": summary,
            "why_it_matters": "Heirloom should cite research instead of inventing a life.",
            "confidence": confidence,
            "citations": [{"title": "Voice notes", "url": "https://example.test/voice", "locator": ""}],
            "source_url": "https://example.test/voice",
            "source_title": "Voice cloning and consent",
            "source_date": "2026-03-18",
            "engine": "local",
        }]
    }), encoding="utf-8")


def test_unrelated_question_leaves_the_prompt_alone(tmp_path):
    path = tmp_path / "approved.json"
    _write(path, "Voice cloning needs consent and a visible citation.")
    system = "CORE\nSTABLE FACTS\nPASSAGES"
    assert study_prompt_block("what did we have for breakfast", path=path) == ""
    assert attach_study_to_prompt(system, "what did we have for breakfast", path=path) == system


def test_related_question_cites_the_source_and_is_not_biography(tmp_path):
    path = tmp_path / "approved.json"
    _write(path, "Voice cloning needs consent and a visible citation.")
    block = study_prompt_block("how should voice cloning handle consent", path=path)
    assert "https://example.test/voice" in block
    assert "not their life" in block
    assert "Voice cloning and consent" in block
    attached = attach_study_to_prompt("SYSTEM", "how should voice cloning handle consent", path=path)
    assert attached.startswith("SYSTEM\n\nAPPROVED STUDY")


def test_missing_and_low_confidence_add_nothing(tmp_path):
    missing = tmp_path / "nope.json"
    assert study_prompt_block("voice cloning consent", path=missing) == ""
    low = tmp_path / "low.json"
    _write(low, "Voice cloning needs consent and a visible citation.", confidence=0.2)
    assert study_prompt_block("voice cloning consent", path=low) == ""
