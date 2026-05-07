"""Tests for textproc.normalize.

These avoid heavy ML deps; they only require the `regex` and
`indic-nlp-library` packages. Run with: pytest tests/test_normalize.py
"""
from __future__ import annotations

import unicodedata

import pytest

from sarathi.textproc.normalize import normalize


def test_empty_input():
    assert normalize("") == ""
    assert normalize("   \n\t") == ""


def test_idempotent_english():
    s = "Hello   world.\nThis is a test."
    once = normalize(s, lang="en")
    twice = normalize(once, lang="en")
    assert once == twice


def test_idempotent_gujarati():
    pytest.importorskip("indicnlp")
    s = "નમસ્તે દુનિયા. આ એક પરીક્ષણ છે."
    once = normalize(s, lang="gu")
    twice = normalize(once, lang="gu")
    assert once == twice


def test_nfc_normalization():
    # Decomposed form: 'કા' = ક (U+0915) + ા (U+0ABE) when composed,
    # but Devanagari doesn't decompose this. Use a Latin example that
    # *does* decompose to verify NFC pathway.
    decomposed = "café"  # 'café' in NFD
    out = normalize(decomposed, lang="en")
    assert out == unicodedata.normalize("NFC", "café")


def test_whitespace_collapse_preserves_paragraphs():
    s = "First paragraph.\n\n\nSecond  paragraph    here.\n   \n\nThird."
    out = normalize(s, lang="en")
    assert "\n\n\n" not in out
    assert out.count("\n\n") == 2  # three paragraphs → two breaks


def test_whitespace_collapses_runs():
    s = "many    spaces\t\there"
    out = normalize(s, lang="en")
    assert out == "many spaces here"


def test_strips_stray_zwj():
    # ZWJ between two unrelated Latin chars is meaningless → strip.
    s = "a‍bc"
    out = normalize(s, lang="en")
    assert out == "abc"


def test_preserves_zwj_around_virama():
    # Gujarati virama is U+0ACD. ZWJ adjacent to virama is grammatical
    # (forces conjunct vs. half-form). Must NOT be stripped.
    pytest.importorskip("indicnlp")
    s = "ક્‍ષ"  # k + virama + ZWJ + sha → grammatical conjunct form
    out = normalize(s, lang="gu")
    assert "‍" in out
