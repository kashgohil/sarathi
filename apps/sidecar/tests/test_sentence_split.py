from __future__ import annotations

import pytest

from sarathi.textproc.sentence_split import split_sentences


def test_empty():
    assert split_sentences("") == []
    assert split_sentences("   \n") == []


def test_english_basic():
    s = "Hello world. This is sarathi. How are you?"
    out = split_sentences(s, lang="en")
    assert len(out) == 3
    assert out[0] == "Hello world."


def test_english_handles_abbreviations():
    s = "Dr. Patel works at Inc. Corp. He is a doctor."
    out = split_sentences(s, lang="en")
    # pysbd should not split on "Dr." or "Inc."
    assert len(out) == 2


def test_gujarati_purna_viram():
    pytest.importorskip("indicnlp")
    s = "નમસ્તે દુનિયા। આ એક પરીક્ષણ છે। તમે કેમ છો?"
    out = split_sentences(s, lang="gu")
    assert len(out) == 3
    assert out[0].startswith("નમસ્તે")


def test_gujarati_mixed_punctuation():
    pytest.importorskip("indicnlp")
    s = "પહેલું વાક્ય. બીજું વાક્ય? ત્રીજું વાક્ય!"
    out = split_sentences(s, lang="gu")
    assert len(out) == 3
