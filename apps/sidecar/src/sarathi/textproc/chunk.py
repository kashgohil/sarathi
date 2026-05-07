"""Sentence-anchored, token-counted, grapheme-safe chunking.

Why this exists rather than reaching for langchain/llama-index splitters:
- They count by characters or naive whitespace tokens, which mis-sizes
  Gujarati (very different bytes-per-token ratio than English).
- They split mid-sentence on token-budget overflow; we always snap to
  sentence boundaries because BGE-M3 retrieval quality drops measurably
  on mid-sentence chunks.
- They're not grapheme-cluster aware; slicing Gujarati strings by char
  index can split conjuncts.

This implementation:
- Counts tokens with the embedding model's actual tokenizer (XLM-R for
  BGE-M3). No heuristics.
- Always anchors boundaries at sentence ends from sentence_split().
- Overlaps by max(overlap_tokens, overlap_sentences) to keep semantic
  continuity across chunks.
- Treats grapheme clusters as the atomic character unit anywhere we
  need to compare or slice text by "characters".

A `Chunk` carries metadata downstream needs (lang, source, etc.) plus
the parent context (doc title, section path) prepended at embed time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import regex as re

from sarathi.textproc.sentence_split import split_sentences

# Grapheme cluster pattern. Use this any time you need to count or slice
# "characters" in Indic text — codepoint-level slicing corrupts conjuncts.
_GRAPHEME = re.compile(r"\X")


def grapheme_count(s: str) -> int:
    """Count grapheme clusters (user-perceived characters)."""
    return sum(1 for _ in _GRAPHEME.finditer(s))


@dataclass(frozen=True)
class ChunkConfig:
    target_tokens: int = 400
    max_tokens: int = 512
    overlap_tokens: int = 50
    overlap_sentences: int = 1
    embed_tokenizer: str = "BAAI/bge-m3"


@dataclass
class Chunk:
    text: str
    token_count: int
    sentence_range: tuple[int, int]  # [start, end) into the input sentence list
    lang: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@lru_cache(maxsize=2)
def _get_tokenizer(name: str):
    try:
        from transformers import AutoTokenizer
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("transformers is required for chunk token counting.") from e
    # use_fast=True picks XLMRobertaTokenizerFast for BGE-M3.
    return AutoTokenizer.from_pretrained(name, use_fast=True)


def _count_tokens(text: str, tokenizer) -> int:
    # No special tokens — we're counting content, not preparing model input.
    return len(tokenizer.encode(text, add_special_tokens=False))


def _take_overlap_sentences(
    sentences: list[str], token_counts: list[int], cfg: ChunkConfig
) -> tuple[list[str], list[int], int]:
    """From the end of `sentences`, take enough trailing sentences to satisfy
    overlap policy: at least `overlap_sentences` AND at least `overlap_tokens`.

    Returns (overlap_sentences, their token_counts, total_tokens).
    """
    if not sentences:
        return [], [], 0

    chosen: list[str] = []
    chosen_counts: list[int] = []
    total = 0

    # Walk backwards.
    for sent, n in zip(reversed(sentences), reversed(token_counts), strict=True):
        chosen.insert(0, sent)
        chosen_counts.insert(0, n)
        total += n
        if len(chosen) >= cfg.overlap_sentences and total >= cfg.overlap_tokens:
            break

    return chosen, chosen_counts, total


def chunk_text(
    text: str,
    *,
    lang: str | None = None,
    config: ChunkConfig | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """Split text into embedding-ready chunks.

    Args:
        text: pre-normalized text (call normalize() first).
        lang: ISO 639-1 hint — used for sentence splitting and stored on chunks.
        config: optional override; defaults are tuned for BGE-M3.
        metadata: extra key/values copied onto every produced chunk.

    Returns:
        List of Chunk. Empty if text yields no sentences.
    """
    cfg = config or ChunkConfig()
    meta = dict(metadata or {})

    sentences = split_sentences(text, lang=lang)
    if not sentences:
        return []

    tokenizer = _get_tokenizer(cfg.embed_tokenizer)
    sent_tokens = [_count_tokens(s, tokenizer) for s in sentences]

    chunks: list[Chunk] = []

    # `cur_*` describe the chunk currently being assembled.
    cur_sents: list[str] = []
    cur_counts: list[int] = []
    cur_total: int = 0
    cur_start_idx: int = 0  # index into `sentences`

    def flush(end_idx: int) -> None:
        if not cur_sents:
            return
        chunks.append(
            Chunk(
                text=" ".join(cur_sents),
                token_count=cur_total,
                sentence_range=(cur_start_idx, end_idx),
                lang=lang,
                metadata=dict(meta),
            )
        )

    i = 0
    while i < len(sentences):
        sent = sentences[i]
        n = sent_tokens[i]

        # Pathological single sentence > max_tokens. Emit as its own chunk
        # rather than dropping or hard-slicing (which would break Indic).
        if n > cfg.max_tokens and not cur_sents:
            chunks.append(
                Chunk(
                    text=sent,
                    token_count=n,
                    sentence_range=(i, i + 1),
                    lang=lang,
                    metadata={**meta, "oversized": True},
                )
            )
            i += 1
            cur_start_idx = i
            continue

        # Would adding this sentence exceed the target? If we have room
        # within max_tokens, keep packing. Otherwise flush.
        projected = cur_total + n
        room_for_more = projected <= cfg.target_tokens
        within_hard_cap = projected <= cfg.max_tokens

        if not cur_sents or room_for_more:
            cur_sents.append(sent)
            cur_counts.append(n)
            cur_total = projected
            i += 1
            continue

        # Past target. Pack one more if it stays under max_tokens AND the
        # current chunk is meaningfully under target (avoids creating tiny
        # chunks). Otherwise, flush now.
        if within_hard_cap and cur_total < int(cfg.target_tokens * 0.85):
            cur_sents.append(sent)
            cur_counts.append(n)
            cur_total = projected
            i += 1
            continue

        # Flush current chunk and start a new one with overlap.
        flush(i)

        overlap_sents, overlap_counts, overlap_total = _take_overlap_sentences(
            cur_sents, cur_counts, cfg
        )
        # `cur_start_idx` for the new chunk = (end of previous) - len(overlap)
        cur_start_idx = i - len(overlap_sents)
        cur_sents = list(overlap_sents)
        cur_counts = list(overlap_counts)
        cur_total = overlap_total
        # `i` stays the same — we'll add `sent` on the next loop iteration.

    flush(len(sentences))
    return chunks
