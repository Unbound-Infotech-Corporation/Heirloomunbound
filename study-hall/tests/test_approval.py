"""Nothing reaches the twin until the owner files it. Ideas never change code."""
from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from studyhall.app import create_app
from studyhall.hall import Hall


def _draft(hall: Hall) -> str:
    added = hall.add_sample()
    assert added["stored"] is True
    source_id = added["source"]["source_id"]

    async def _study():
        return await hall.study(source_id, engine="practice")

    import asyncio

    result = asyncio.run(_study())
    assert result["engine"] == "practice"
    assert hall.store.read_knowledge() == []
    return result["lesson"]["lesson_id"], result["proposals"][0]["proposal_id"]


def test_draft_is_not_in_twin_knowledge(tmp_path):
    hall = Hall(tmp_path)
    lesson_id, _proposal_id = _draft(hall)
    assert hall.store.read_knowledge() == []
    assert not (tmp_path / "knowledge" / "approved.json").exists() or hall.store.read_knowledge() == []
    lesson = next(item for item in hall.lessons() if item["lesson_id"] == lesson_id)
    assert lesson["status"] == "draft"
    assert lesson["source_url"] == "sample://voice-and-memory"
    assert lesson["source_title"]
    assert lesson["citations"]


def test_filing_writes_provenance_and_a_second_file_is_a_no_op(tmp_path):
    hall = Hall(tmp_path)
    lesson_id, _proposal_id = _draft(hall)
    filed = hall.file_lesson(lesson_id)
    assert filed["already"] is False
    assert filed["receipt"]["code_changed"] is False
    assert filed["receipt"]["action"] == "file_lesson"
    assert "knowledge/approved.json" in filed["receipt"]["wrote"]
    lessons = hall.store.read_knowledge()
    assert len(lessons) == 1
    assert lessons[0]["source_url"] == "sample://voice-and-memory"
    assert lessons[0]["source_title"]
    assert lessons[0]["citations"]
    assert lessons[0]["receipt_id"] == filed["receipt"]["receipt_id"]
    again = hall.file_lesson(lesson_id)
    assert again["already"] is True
    assert again["receipt"]["receipt_id"] == filed["receipt"]["receipt_id"]
    assert len(hall.store.read_knowledge()) == 1


def test_reject_does_not_file(tmp_path):
    hall = Hall(tmp_path)
    lesson_id, _proposal_id = _draft(hall)
    rejected = hall.reject_lesson(lesson_id)
    assert rejected["receipt"]["action"] == "reject_lesson"
    assert hall.store.read_knowledge() == []
    assert "twin study knowledge" not in rejected["receipt"]["note"] or "Nothing was written" in rejected["receipt"]["note"]


def test_accepting_an_idea_does_not_touch_twin_code(tmp_path):
    hall = Hall(tmp_path)
    _lesson_id, proposal_id = _draft(hall)
    sentinel = tmp_path / "twin" / "model_router.py"
    sentinel.parent.mkdir()
    sentinel.write_text("ORIGINAL TWIN CODE\n", encoding="utf-8")
    digest = hashlib.sha256(sentinel.read_bytes()).hexdigest()
    before = {path.relative_to(hall.store.root).as_posix() for path in hall.store.root.rglob("*") if path.is_file()}
    accepted = hall.accept_proposal(proposal_id)
    assert accepted["receipt"]["code_changed"] is False
    assert accepted["receipt"]["wrote"] == ["proposals.json", "receipts.json"]
    assert hashlib.sha256(sentinel.read_bytes()).hexdigest() == digest
    assert sentinel.read_text(encoding="utf-8") == "ORIGINAL TWIN CODE\n"
    after = {path.relative_to(hall.store.root).as_posix() for path in hall.store.root.rglob("*") if path.is_file()}
    assert after - before <= {"proposals.json", "receipts.json"}
    assert hall.store.read_knowledge() == []
    again = hall.accept_proposal(proposal_id)
    assert again["already"] is True


def test_http_study_does_not_file_until_the_owner_does(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        added = client.post("/api/library/sample")
        assert added.status_code == 200
        source_id = added.json()["source"]["source_id"]
        studied = client.post("/api/study", json={"source_id": source_id, "engine": "practice"})
        assert studied.status_code == 200
        body = studied.json()
        assert body["engine"] == "practice"
        assert body["lesson"]["status"] == "draft"
        knowledge = client.get("/api/knowledge")
        assert knowledge.json()["lessons"] == []
        lesson_id = body["lesson"]["lesson_id"]
        proposal_id = body["proposals"][0]["proposal_id"]
        filed = client.post(f"/api/lessons/{lesson_id}/file")
        assert filed.status_code == 200
        receipt = filed.json()["receipt"]
        assert receipt["code_changed"] is False
        stored = client.get("/api/knowledge").json()["lessons"]
        assert stored[0]["source_url"] == "sample://voice-and-memory"
        assert stored[0]["summary"]
        idea = client.post(f"/api/queue/{proposal_id}/accept")
        assert idea.status_code == 200
        assert idea.json()["receipt"]["code_changed"] is False
        raw = json.loads((tmp_path / "knowledge" / "approved.json").read_text(encoding="utf-8"))
        assert raw["lessons"][0]["lesson_id"] == lesson_id
