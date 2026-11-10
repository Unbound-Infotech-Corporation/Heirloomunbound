"""Study Hall lessons stay out of the prompt until they are filed and relevant."""
from __future__ import annotations

import json

from study_knowledge import attach_study_to_prompt, study_prompt_block


def _write(path, summary: str, *, confidence: float = 0.8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "lessons": [{
            "lesson_id": "les_test",
            "summary": summary,
            "why_it_matters": "Heirloom should cite research instead of inventing a life.",
            "confidence": confidence,
            "source_url": "https://example.test/voice",
            "source_title": "Voice cloning and consent",
            "engine": "local",
        }]
    }), encoding="utf-8")


def test_unrelated_question_leaves_the_prompt_alone(tmp_path):
    path = tmp_path / "approved.json"
    _write(path, "Voice cloning needs consent and a visible citation.")
    system = "CORE\nSTABLE FACTS\nPASSAGES"
    assert study_prompt_block("what did we have for breakfast", path=path) == ""
    assert attach_study_to_prompt(system, "what did we have for breakfast", path=path) == system


def test_related_question_cites_the_source(tmp_path):
    path = tmp_path / "approved.json"
    _write(path, "Voice cloning needs consent and a visible citation.")
    block = study_prompt_block("how should voice cloning handle consent", path=path)
    assert "https://example.test/voice" in block
    assert "not their life" in block
