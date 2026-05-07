"""Hybrid retrieval: dense (LanceDB) + sparse (in-process), fused with RRF.

Reciprocal Rank Fusion (Cormack et al. 2009):
    score(d) = Σ_i 1 / (k + rank_i(d))
where rank starts at 1 and `k` is a smoothing constant (default 60 in
the literature; we expose it via config).

The sparse channel scores BGE-M3's lexical weights as a dot product
between query weights and chunk weights. This is BM25-shaped without
needing a dedicated index — at our scale (<100k chunks) the linear
scan is cheap and avoids a second storage system.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FusedHit:
    chunk_id: str
    score: float
    rank: int
    components: dict[str, int]  # channel name → rank in that channel (1-indexed)


def sparse_dot(q: dict[int, float], d: dict[int, float]) -> float:
    if not q or not d:
        return 0.0
    # Iterate over the smaller dict for speed.
    if len(q) > len(d):
        q, d = d, q
    s = 0.0
    for tok, w in q.items():
        if tok in d:
            s += w * d[tok]
    return s


def rrf_fuse(
    rankings: dict[str, list[str]],
    *,
    k: int = 60,
    final_k: int | None = None,
) -> list[FusedHit]:
    """Fuse multiple ranked lists into one.

    Args:
        rankings: channel name → ordered list of chunk_ids (best first).
        k: RRF smoothing constant.
        final_k: cap on output length.

    Returns:
        FusedHits sorted by descending score, ties broken by chunk_id.
    """
    accum: dict[str, FusedHit] = {}

    for channel, ranked_ids in rankings.items():
        for idx, cid in enumerate(ranked_ids):
            rank = idx + 1
            contrib = 1.0 / (k + rank)
            hit = accum.get(cid)
            if hit is None:
                hit = FusedHit(chunk_id=cid, score=0.0, rank=0, components={})
                accum[cid] = hit
            hit.score += contrib
            hit.components[channel] = rank

    fused = sorted(accum.values(), key=lambda h: (-h.score, h.chunk_id))
    for i, h in enumerate(fused):
        h.rank = i + 1
    if final_k is not None:
        fused = fused[:final_k]
    return fused


def hybrid_search(
    store,
    *,
    query_dense: list[float],
    query_sparse: dict[int, float] | None,
    dense_k: int,
    sparse_k: int,
    rrf_k: int,
    final_k: int,
) -> list[FusedHit]:
    """One-shot hybrid search against a LanceStore.

    Pulls top dense_k from LanceDB, scores all chunks in-process for the
    sparse channel (cheap), and fuses via RRF.
    """
    # Dense channel.
    dense_hits = store.search_dense(query_dense, k=dense_k)
    dense_ranked = [r["id"] for r in dense_hits]

    # Sparse channel.
    sparse_ranked: list[str] = []
    if query_sparse:
        scored = []
        for cid, doc_sparse in store.all_sparse():
            s = sparse_dot(query_sparse, doc_sparse)
            if s > 0:
                scored.append((cid, s))
        scored.sort(key=lambda x: -x[1])
        sparse_ranked = [cid for cid, _ in scored[:sparse_k]]

    return rrf_fuse(
        {"dense": dense_ranked, "sparse": sparse_ranked},
        k=rrf_k,
        final_k=final_k,
    )
