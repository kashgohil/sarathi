"""Cross-encoder reranking via bge-reranker-v2-m3.

The reranker takes (query, doc) pairs and returns a relevance score
that is materially better than first-stage retrieval scores, especially
for cross-lingual cases (English query → Gujarati passage).

Cost: ~50–200ms per (query, doc) batch on M-series. We rerank only the
top-K from RRF (usually 20) and keep the top-N (usually 5–8) for the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass
class RerankedHit:
    chunk_id: str
    score: float
    rank: int


@lru_cache(maxsize=1)
def _load_reranker(model_name: str, use_fp16: bool):
    try:
        from FlagEmbedding import FlagReranker
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "FlagEmbedding is required for reranking. Install with: uv sync --extra ml"
        ) from e
    from sarathi.progress import loading

    with loading("retrieve.rerank", f"Reranker ({model_name})", approx_mb=1100):
        return FlagReranker(model_name, use_fp16=use_fp16)


def rerank(
    query: str,
    candidates: list[tuple[str, str]],  # [(chunk_id, text), ...]
    *,
    model: str = "BAAI/bge-reranker-v2-m3",
    use_fp16: bool = True,
    top_k: int | None = None,
) -> list[RerankedHit]:
    """Rerank `candidates` by cross-encoder score.

    Returns the candidates sorted by score descending. If `top_k` is set,
    truncates to that length.
    """
    if not candidates:
        return []

    m = _load_reranker(model, use_fp16)
    pairs = [[query, text] for _, text in candidates]
    scores = m.compute_score(pairs, normalize=True)
    if not isinstance(scores, list):
        scores = [scores]

    ranked = [(cid, float(s)) for (cid, _), s in zip(candidates, scores, strict=True)]
    ranked.sort(key=lambda x: -x[1])
    if top_k is not None:
        ranked = ranked[:top_k]

    return [RerankedHit(chunk_id=cid, score=s, rank=i + 1) for i, (cid, s) in enumerate(ranked)]
