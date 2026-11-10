"""In-place installs replace code folders and keep the owner's data."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from update_install import update_tree


def test_update_replaces_code_and_keeps_owner_files(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "HeirloomStudyHall"
    (source / "studyhall").mkdir(parents=True)
    (source / "studyhall" / "app.py").write_text("NEW", encoding="utf-8")
    (source / "studyhall" / "__pycache__").mkdir()
    (source / "studyhall" / "__pycache__" / "app.pyc").write_bytes(b"pyc")
    (source / "tests").mkdir()
    (source / "tests" / "test_research.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")
    (source / "run.py").write_text("print(1)\n", encoding="utf-8")
    (source / "config.json").write_text('{"from": "source"}\n', encoding="utf-8")

    (dest / "studyhall").mkdir(parents=True)
    (dest / "studyhall" / "app.py").write_text("OLD", encoding="utf-8")
    (dest / "studyhall" / "studyhall").mkdir()
    (dest / "studyhall" / "studyhall" / "app.py").write_text("NESTED", encoding="utf-8")
    (dest / "tests").mkdir()
    (dest / "tests" / "old_test.py").write_text("old", encoding="utf-8")
    (dest / "data" / "knowledge").mkdir(parents=True)
    (dest / "data" / "knowledge" / "approved.json").write_text('{"lessons":[{"keep":true}]}', encoding="utf-8")
    (dest / "ollama-models").mkdir()
    (dest / "ollama-models" / "blob").write_text("model", encoding="utf-8")
    (dest / "logs").mkdir()
    (dest / "logs" / "run.log").write_text("log", encoding="utf-8")
    (dest / "setup-models.ps1").write_text("# owner models\n", encoding="utf-8")
    (dest / "Launch-StudyHall.ps1").write_text("# stale launcher\n", encoding="utf-8")
    (dest / "config.json").write_text('{"owner": true}\n', encoding="utf-8")

    report = update_tree(source, dest)

    assert (dest / "studyhall" / "app.py").read_text(encoding="utf-8") == "NEW"
    assert not (dest / "studyhall" / "studyhall").exists()
    assert not (dest / "studyhall" / "__pycache__").exists()
    assert (dest / "tests" / "test_research.py").is_file()
    assert not (dest / "tests" / "old_test.py").exists()
    assert not (dest / "tests" / "tests").exists()
    assert json.loads((dest / "data" / "knowledge" / "approved.json").read_text(encoding="utf-8"))["lessons"][0]["keep"] is True
    assert (dest / "ollama-models" / "blob").read_text(encoding="utf-8") == "model"
    assert (dest / "logs" / "run.log").read_text(encoding="utf-8") == "log"
    assert (dest / "setup-models.ps1").read_text(encoding="utf-8").startswith("# owner")
    assert not (dest / "Launch-StudyHall.ps1").exists()
    assert json.loads((dest / "config.json").read_text(encoding="utf-8"))["owner"] is True
    assert "Launch-StudyHall.ps1" in report["removed_obsolete"]
    assert "studyhall" in report["copied"]
    assert "data" not in report["copied"]


def test_fresh_install_copies_config_and_does_not_nest(tmp_path):
    source = tmp_path / "src"
    dest = tmp_path / "fresh"
    (source / "studyhall").mkdir(parents=True)
    (source / "studyhall" / "app.py").write_text("NEW", encoding="utf-8")
    (source / "config.json").write_text('{"from": "source"}\n', encoding="utf-8")

    update_tree(source, dest)

    assert (dest / "studyhall" / "app.py").read_text(encoding="utf-8") == "NEW"
    assert not (dest / "studyhall" / "studyhall").exists()
    assert json.loads((dest / "config.json").read_text(encoding="utf-8"))["from"] == "source"
    assert (dest / "data" / "knowledge").is_dir()
    assert (dest / "ollama-models").is_dir()
    assert (dest / "logs").is_dir()


def test_running_from_the_install_folder_does_not_delete_it(tmp_path):
    folder = tmp_path / "HeirloomStudyHall"
    (folder / "studyhall").mkdir(parents=True)
    (folder / "studyhall" / "app.py").write_text("KEEP", encoding="utf-8")
    (folder / "data").mkdir()
    (folder / "data" / "note.txt").write_text("mine", encoding="utf-8")

    report = update_tree(folder, folder)

    assert (folder / "studyhall" / "app.py").read_text(encoding="utf-8") == "KEEP"
    assert (folder / "data" / "note.txt").read_text(encoding="utf-8") == "mine"
    assert report["copied"] == []
