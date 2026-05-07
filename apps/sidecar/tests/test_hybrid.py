"""RRF / sparse_dot tests — pure-Python, no ML deps."""
from __future__ import annotations

from sarathi.retrieve.hybrid import rrf_fuse, sparse_dot


def test_sparse_dot_empty():
    assert sparse_dot({}, {1: 0.5}) == 0.0
    assert sparse_dot({1: 0.5}, {}) == 0.0


def test_sparse_dot_overlap():
    q = {1: 0.5, 2: 0.5}
    d = {2: 1.0, 3: 1.0}
    assert sparse_dot(q, d) == 0.5


def test_rrf_single_channel():
    rankings = {"dense": ["a", "b", "c"]}
    fused = rrf_fuse(rankings, k=60)
    assert [h.chunk_id for h in fused] == ["a", "b", "c"]
    # Score monotonically decreasing.
    assert fused[0].score > fused[1].score > fused[2].score


def test_rrf_two_channels_agree():
    rankings = {
        "dense": ["a", "b", "c"],
        "sparse": ["a", "b", "c"],
    }
    fused = rrf_fuse(rankings)
    # `a` beats `b` beats `c` in both, so order is preserved and score doubled.
    assert [h.chunk_id for h in fused] == ["a", "b", "c"]


def test_rrf_two_channels_disagree():
    rankings = {
        "dense": ["a", "b", "c"],
        "sparse": ["c", "b", "a"],
    }
    fused = rrf_fuse(rankings)
    # `b` is rank 2 in both → highest score. `a` and `c` tie.
    assert fused[0].chunk_id == "b"


def test_rrf_final_k_truncates():
    rankings = {"dense": list("abcdef")}
    fused = rrf_fuse(rankings, final_k=3)
    assert len(fused) == 3
    assert fused[-1].chunk_id == "c"


def test_rrf_components_recorded():
    rankings = {
        "dense": ["a", "b"],
        "sparse": ["b", "a"],
    }
    fused = rrf_fuse(rankings)
    by_id = {h.chunk_id: h for h in fused}
    assert by_id["a"].components == {"dense": 1, "sparse": 2}
    assert by_id["b"].components == {"dense": 2, "sparse": 1}
