"""Offline writing assistant, dictionary, and paste approval."""
from __future__ import annotations

import pytest

from writing_assistant import (
    PasteRefused,
    WritingEngineRefused,
    apply_fixes,
    approve_paste,
    check_text,
    check_with_engine,
    lookup,
    paste_back,
    propose_paste,
    rewrite,
)


def _kinds(text: str, surface: str = "draft") -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for issue in check_text(text, surface=surface)["issues"]:
        found.setdefault(issue["kind"], []).append(issue["message"])
    return found


def test_spelling_grammar_style_tone_and_clarity():
    spelling = check_text("Please recieve the note.")
    assert any(issue["suggestions"] == ["receive"] for issue in spelling["issues"])
    assert all(issue["kind"] != "spelling" for issue in check_text("It is a nice day.")["issues"])
    missed = check_text("Check the speling here.")
    assert any(issue["suggestions"] == ["spelling"] for issue in missed["issues"])
    assert "grammar" in _kinds("Its a nice day and its going well.")
    assert "grammar" in _kinds("your going to like it")
    assert "grammar" in _kinds("I ate a apple")
    assert "grammar" not in _kinds("It took an hour")
    assert "style" in _kinds("This is very clear.")
    assert "tone" in _kinds("PLEASE STOP NOW!!")
    long_sentence = " ".join(["word"] * 33) + "."
    assert "clarity" in _kinds(long_sentence)
    comment = check_text("The helper_name is recieve.", surface="code_comment")
    assert any(issue["suggestions"] == ["receive"] for issue in comment["issues"])
    assert all("helper_name" not in (issue["message"] + "".join(issue["suggestions"])) for issue in comment["issues"])


def test_one_click_fix_and_rewrites():
    checked = check_text("I ate a apple.")
    grammar = [issue for issue in checked["issues"] if issue["kind"] == "grammar"]
    assert apply_fixes("I ate a apple.", grammar).startswith("I ate an apple")
    assert rewrite("This is very late in order to help.", "shorter")["text"] == "This is late to help."
    friendly = rewrite("I am sure I would help and I do not mind.", "friendlier")["text"]
    assert "I'm" in friendly and "I'd" in friendly and "don't" in friendly
    formal = rewrite("I don't wanna go.", "formal")["text"]
    assert formal == "I do not want to go."
    with pytest.raises(WritingEngineRefused):
        rewrite("Hello", "cloud")


def test_dictionary_and_hosted_engines():
    happy = lookup("Happy")
    assert happy["found"] is True
    assert "sad" in happy["antonyms"]
    assert "glad" in happy["synonyms"]
    missing = lookup("xyzzy")
    assert missing["found"] is False
    with pytest.raises(WritingEngineRefused):
        check_with_engine("Hello", engine="languagetool", languagetool_url="https://api.languagetool.org")
    with pytest.raises(WritingEngineRefused):
        check_with_engine("Hello", engine="gemini")
    local = check_with_engine("Hello", engine="languagetool", languagetool_url="http://127.0.0.1:8081")
    assert local["engine"] == "languagetool-local"


def test_paste_back_waits_for_approval():
    proposal = propose_paste("This is very long.", "shorter")
    assert proposal["approved"] is False
    assert proposal["chord"] == "Ctrl+Alt+H"
    with pytest.raises(PasteRefused):
        paste_back(proposal)
    approved = approve_paste(proposal)
    assert paste_back(approved) == "This is long."
