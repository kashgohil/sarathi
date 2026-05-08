from __future__ import annotations

from sarathi.qdetect.heuristic import detect_question_heuristic


def test_empty():
    r = detect_question_heuristic("")
    assert not r.is_question
    assert r.confidence == 0.0


def test_trailing_question_mark_en():
    r = detect_question_heuristic("Are we shipping today?")
    assert r.is_question
    assert r.confidence >= 0.9
    assert r.reason == "trailing_qmark"


def test_trailing_question_mark_gu():
    r = detect_question_heuristic("તમે કેમ છો?", lang="gu")
    assert r.is_question
    assert r.confidence >= 0.9


def test_en_wh_lead():
    r = detect_question_heuristic("What is the onboarding process")
    assert r.is_question
    assert r.reason == "en_wh_lead"


def test_en_modal_lead():
    r = detect_question_heuristic("Can you show the dashboard")
    assert r.is_question
    assert r.reason == "en_modal_lead"


def test_gu_interrogative_pronoun():
    r = detect_question_heuristic("શું આ સાચું છે", lang="gu")
    assert r.is_question
    assert r.reason == "gu_interrogative"


def test_statement_returns_false():
    r = detect_question_heuristic("This is a statement.")
    assert not r.is_question


def test_gu_statement_returns_false():
    r = detect_question_heuristic("આ એક નિવેદન છે.", lang="gu")
    assert not r.is_question
