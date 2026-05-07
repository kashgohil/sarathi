from __future__ import annotations

from sarathi.ingest.lang_id import _gujarati_ratio, detect_lang


def test_gu_ratio_pure_gujarati():
    assert _gujarati_ratio("નમસ્તે") > 0.9


def test_gu_ratio_mixed_eng_dominant():
    assert _gujarati_ratio("This is mostly English with one ગ char") < 0.1


def test_gu_ratio_empty():
    assert _gujarati_ratio("") == 0.0
    assert _gujarati_ratio("   ") == 0.0


def test_detect_gu_without_fasttext():
    # Even with no fasttext model, Gujarati script is detected by ratio.
    assert detect_lang("નમસ્તે દુનિયા") == "gu"


def test_detect_falls_back_to_default():
    # Latin text with no fasttext model → fallback.
    assert detect_lang("Hello world", fallback="en") == "en"
    assert detect_lang("", fallback="en") == "en"


def test_detect_short_mixed_prefers_gu_when_above_threshold():
    # 5 of 10 non-space chars Gujarati → above 10% threshold.
    text = "abcde કખગઘચ"
    assert detect_lang(text, gu_threshold=0.4) == "gu"
    # Higher threshold → no longer gu, falls back.
    assert detect_lang(text, gu_threshold=0.9, fallback="en") == "en"
