"""BGE-M3 embeddings — dense + sparse in one pass.

BGE-M3 is multilingual (100+ languages incl. Gujarati) and emits three
representations from a single forward pass:
  - dense vector (1024 d) — for cosine semantic search
  - sparse weights — token → weight, for lexical / BM25-like search
  - colbert vectors — multi-vector, for late-interaction reranking (unused here)

We use dense + sparse, fused at retrieval time via RRF.

This module is a thin wrapper around FlagEmbedding. The model loads
lazily and is cached process-wide.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any


@dataclass
class M3Output:
    dense: list[float]
    sparse: dict[int, float]  # token-id → weight
    text: str


@lru_cache(maxsize=1)
def _load_model(model_name: str, use_fp16: bool):
    try:
        from FlagEmbedding import BGEM3FlagModel
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "FlagEmbedding is required for embeddings. "
            "Install with: uv sync --extra ml"
        ) from e
    from sarathi.progress import hf_repo_cache, loading

    with loading(
        "embed.bge_m3",
        f"BGE-M3 ({model_name})",
        approx_mb=2300,
        cache_dirs=[hf_repo_cache(model_name)],
    ):
        # use_fp16=True → ~2x speed and minimal quality loss on M-series.
        return BGEM3FlagModel(model_name, use_fp16=use_fp16)


def embed(
    texts: list[str],
    *,
    model: str = "BAAI/bge-m3",
    use_fp16: bool = True,
    batch_size: int = 12,
    max_length: int = 1024,
    return_sparse: bool = True,
) -> list[M3Output]:
    """Embed a batch of strings.

    Args:
        texts: pre-normalized input strings.
        model: HF model id.
        use_fp16: half-precision on supported hardware.
        batch_size: per-call batch size; tune to your RAM headroom.
        max_length: token cap (chunks are pre-sized to <=512, this gives slack).
        return_sparse: include sparse weights. Set False if you only need dense.

    Returns:
        List of M3Output, one per input, preserving order.
    """
    if not texts:
        return []

    m = _load_model(model, use_fp16)
    out = m.encode(
        texts,
        batch_size=batch_size,
        max_length=max_length,
        return_dense=True,
        return_sparse=return_sparse,
        return_colbert_vecs=False,
    )

    dense_vecs = out["dense_vecs"]
    sparse_list = out.get("lexical_weights", []) if return_sparse else []

    results: list[M3Output] = []
    for i, text in enumerate(texts):
        dense = dense_vecs[i].tolist() if hasattr(dense_vecs[i], "tolist") else list(dense_vecs[i])
        sparse = {}
        if return_sparse and i < len(sparse_list):
            # FlagEmbedding returns {token_id (str): weight}. Cast keys to int.
            sparse = {int(k): float(v) for k, v in sparse_list[i].items()}
        results.append(M3Output(dense=dense, sparse=sparse, text=text))
    return results


def embed_query(
    query: str,
    *,
    model: str = "BAAI/bge-m3",
    use_fp16: bool = True,
) -> M3Output:
    return embed([query], model=model, use_fp16=use_fp16)[0]


def embed_config_from(cfg: Any) -> dict:
    s = cfg.section("embed")
    return {
        "model": s.get("model", "BAAI/bge-m3"),
        # hybrid=True → return both dense and sparse
    }
