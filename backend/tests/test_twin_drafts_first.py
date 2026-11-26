"""Writing help gets a draft first, not a round of questions."""
from pathlib import Path


def test_twin_prompt_asks_for_a_draft_before_questions():
    src = (Path(__file__).resolve().parents[1] / "twin_runtime.py").read_text(encoding="utf-8")
    voice = src[src.index("Voice rules:"):src.index("Your memory tools")]
    assert "write a short first draft right away" in voice
    assert "Don't ask questions before the draft." in voice
