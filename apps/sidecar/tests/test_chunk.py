"""Tests for chunk.py.

These tests require the BGE-M3 tokenizer (XLMRobertaTokenizerFast). The
tokenizer config is small (~5MB); the model weights are not needed.
On first run, transformers downloads the tokenizer from HF Hub.

If you want to run completely offline, point HF_HUB_OFFLINE=1 and ensure
the tokenizer is cached.
"""
from __future__ import annotations

import pytest

from sarathi.textproc.chunk import (
    Chunk,
    ChunkConfig,
    chunk_text,
    grapheme_count,
)
from sarathi.textproc.normalize import normalize

_TRANSFORMERS = pytest.importorskip("transformers")


@pytest.fixture(scope="module")
def small_cfg():
    # Very small config so we can exercise boundary logic on short inputs.
    return ChunkConfig(
        target_tokens=20,
        max_tokens=30,
        overlap_tokens=5,
        overlap_sentences=1,
    )


def test_grapheme_count_counts_clusters_not_codepoints():
    # 'ક્ષ' is one user-perceived character but multiple codepoints.
    assert grapheme_count("ક્ષ") == 1
    assert grapheme_count("abc") == 3
    assert grapheme_count("") == 0


def test_empty_text_yields_no_chunks(small_cfg):
    assert chunk_text("", lang="en", config=small_cfg) == []


def test_short_text_one_chunk(small_cfg):
    text = "Hello world. This is short."
    out = chunk_text(normalize(text, lang="en"), lang="en", config=small_cfg)
    assert len(out) == 1
    assert out[0].sentence_range == (0, 2)
    assert out[0].lang == "en"


def test_long_text_splits_with_overlap(small_cfg):
    # Build text that definitely exceeds the small target.
    sentences = [f"This is sentence number {i} with a few extra words." for i in range(20)]
    text = " ".join(sentences)
    out = chunk_text(normalize(text, lang="en"), lang="en", config=small_cfg)

    assert len(out) > 1
    # Token counts respect the hard cap.
    for c in out:
        assert c.token_count <= small_cfg.max_tokens

    # Adjacent chunks share at least one sentence (overlap).
    for prev, nxt in zip(out, out[1:], strict=False):
        prev_end = prev.sentence_range[1]
        nxt_start = nxt.sentence_range[0]
        assert nxt_start < prev_end, "expected overlap between adjacent chunks"


def test_metadata_carried_per_chunk(small_cfg):
    text = "Sentence one. Sentence two. Sentence three."
    out = chunk_text(
        normalize(text, lang="en"),
        lang="en",
        config=small_cfg,
        metadata={"doc_id": "abc", "page": 1},
    )
    assert all(c.metadata["doc_id"] == "abc" for c in out)
    assert all(c.metadata["page"] == 1 for c in out)


def test_oversized_single_sentence_is_emitted(small_cfg):
    # A single sentence longer than max_tokens — must not be silently dropped.
    long_sent = " ".join(["word"] * 200) + "."
    out = chunk_text(normalize(long_sent, lang="en"), lang="en", config=small_cfg)
    assert len(out) >= 1
    assert any(c.metadata.get("oversized") for c in out)


def test_gujarati_chunking_runs_end_to_end(small_cfg):
    pytest.importorskip("indicnlp")
    paragraph = (
        "નમસ્તે દુનિયા। આ સારથી પરિયોજનાનું પ્રથમ પરીક્ષણ છે। "
        "આપણે દસ્તાવેજો અપલોડ કરીશું। પછી અમે પ્રશ્નો પૂછીશું। "
        "જવાબો અંગ્રેજીમાં મળશે। પણ સંદર્ભો ગુજરાતીમાં મળશે।"
    )
    out = chunk_text(normalize(paragraph, lang="gu"), lang="gu", config=small_cfg)
    assert len(out) >= 1
    for c in out:
        assert c.lang == "gu"
        # Sanity: non-empty, contains Gujarati codepoints.
        assert any("઀" <= ch <= "૿" for ch in c.text)
