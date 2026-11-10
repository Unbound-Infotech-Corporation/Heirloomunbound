"""Panel rounds and the moderator card. Models are mocked."""
from __future__ import annotations

import asyncio
import json

from studyhall.config import default_config
from studyhall.discover import FoundModel, assign_panel
from studyhall.panel import run_study


def _seat_models():
    study = "http://127.0.0.1:11435"
    main = "http://127.0.0.1:11434"
    found = [
        FoundModel("phi4:14b", study, "study", "ollama"),
        FoundModel("mistral-small3.2:24b", study, "study", "ollama"),
        FoundModel("gemma3:27b", study, "study", "ollama"),
        FoundModel("llama3.1:8b", study, "study", "ollama"),
        FoundModel("nomic-embed-text", study, "study", "ollama"),
        FoundModel("mxbai-embed-large", study, "study", "ollama"),
        FoundModel("deepseek-r1:32b", study, "study", "ollama"),
        FoundModel("qwen3:8b", main, "main", "ollama"),
        FoundModel("llama3.3:70b", main, "main", "ollama"),
        FoundModel("gpt-oss:120b", main, "main", "ollama"),
    ]
    return assign_panel(found, default_config())


def test_default_panel_is_a_diverse_local_mix():
    readers, moderator = _seat_models()
    assert [seat.model for seat in readers] == ["phi4:14b", "mistral-small3.2:24b", "gemma3:27b"]
    assert {seat.endpoint for seat in readers} == {"http://127.0.0.1:11435"}
    assert moderator is not None
    assert moderator.model == "llama3.1:8b"
    assert moderator.endpoint == "http://127.0.0.1:11435"
    assert moderator.role == "moderator"
    assert all(not seat.model.startswith("nomic") for seat in readers)


def test_moderator_falls_back_to_the_lightweight_main_model():
    found = [
        FoundModel("phi4:14b", "http://127.0.0.1:11435", "study", "ollama"),
        FoundModel("qwen3:8b", "http://127.0.0.1:11434", "main", "ollama"),
        FoundModel("gpt-oss:120b", "http://127.0.0.1:11434", "main", "ollama"),
    ]
    readers, moderator = assign_panel(found, default_config())
    assert [seat.model for seat in readers] == ["phi4:14b"]
    assert moderator is not None
    assert moderator.model == "qwen3:8b"
    assert moderator.host == "main"


def test_panel_pins_a_cited_lesson_and_queues_ideas():
    readers, moderator = _seat_models()
    calls = []

    async def complete(seat, messages):
        system = messages[0]["content"]
        calls.append((seat.role, seat.model, system.splitlines()[0]))
        if seat.role == "moderator":
            assert "ALREADY FILED" in messages[-1]["content"]
            return json.dumps({
                "summary": "Cite the source and do not treat the note as a life story.",
                "why_it_matters": "The twin stays grounded while it learns a method.",
                "confidence": 0.81,
                "citations": [{"title": "Wrong", "url": "https://example.test/other", "locator": "p. 2"}],
                "proposals": [
                    {"area": "memory", "title": "Keep the URL", "idea": "Store the source beside the lesson."},
                    {"area": "firmware", "title": "Ignore me", "idea": "Not a real area."},
                ],
            })
        if "ROUND: critique" in system:
            return json.dumps({"agree": "Cite it.", "reject": "Hype.", "keep": "Provenance."})
        if "ROUND: revise" in system:
            return json.dumps({"useful": "Cite the source.", "cautions": "Not biography."})
        return json.dumps({"useful": "Keep a citation.", "not_useful": "Hype.", "cautions": "Do not invent a life."})

    source = {
        "title": "Voice cloning, carefully",
        "url": "https://example.test/voice",
        "date": "2026-03-18",
        "text": "A cloned voice needs consent and a citation. " * 30,
    }

    result = asyncio.run(run_study(
        source,
        readers,
        moderator,
        complete,
        already_filed=["An older note"],
    ))
    assert calls[-1][0] == "moderator"
    assert calls[-1][1] == "llama3.1:8b"
    assert len(calls) == 10
    rounds = [call[2] for call in calls]
    assert rounds[:3] == ["ROUND: read", "ROUND: read", "ROUND: read"]
    assert "SECRET" not in json.dumps(calls)
    lesson = result.lesson
    assert "grounded" in lesson["why_it_matters"] or "grounded" in lesson["summary"] or lesson["why_it_matters"]
    assert lesson["summary"]
    assert lesson["why_it_matters"]
    assert lesson["confidence"] == 0.81
    assert any(item["url"] == "https://example.test/voice" for item in lesson["citations"])
    assert lesson["source_title"] == "Voice cloning, carefully"
    assert result.proposals[0]["area"] == "memory"
    assert result.proposals[1]["area"] == "other"
    assert {note.round for note in result.notes} == {"read", "critique", "revise", "pin"}


def test_broken_moderator_still_pins_a_cautious_card():
    readers, moderator = _seat_models()
    readers = readers[:1]

    async def complete(seat, messages):
        if seat.role == "moderator":
            return "I think this is interesting, but here is no card."
        return json.dumps({"useful": "Cite sources before the twin repeats them.", "not_useful": "", "cautions": ""})

    source = {"title": "Notes", "url": "https://example.test/notes", "date": "", "text": "Cite sources. " * 20}
    result = asyncio.run(run_study(source, readers, moderator, complete))
    assert result.lesson["parsed"] is False
    assert result.lesson["confidence"] == 0.35
    assert result.lesson["citations"][0]["url"] == "https://example.test/notes"
    assert result.proposals == []
