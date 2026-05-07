"""Retrieval eval: recall@K and nDCG@K against labeled (query → chunk) pairs.

Reads `eval/datasets/qa.jsonl` and the doc corpus referenced therein.
For each query, runs the sidecar's retrieval pipeline (currently stubbed
in M1; produces real numbers once the [ml] extras are wired up) and
compares the top-K returned chunks against the labeled relevant ones.

Each qa.jsonl row should have:
  {
    "query_id": str,
    "query": str,                    # English or Gujarati
    "doc_set": [<relative path>, ...],
    "expected_citations": [
      {"source": <relative path>, "page": int, "text_contains": "..."},
      ...
    ]
  }

Match logic for relevance: a returned citation is "relevant" if
(source matches AND page matches AND text contains the expected snippet).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path

from harness.sidecar_client import run_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS = REPO_ROOT / "eval" / "datasets"
RESULTS = REPO_ROOT / "eval" / "results"


def is_relevant(citation: dict, expected: list[dict]) -> bool:
    src = citation.get("source", "") or ""
    page = citation.get("page")
    text = citation.get("text", "") or ""
    for e in expected:
        if not src.endswith(e["source"]):
            continue
        if "page" in e and page != e["page"]:
            continue
        if "text_contains" in e and e["text_contains"] not in text:
            continue
        return True
    return False


def recall_at_k(citations: list[dict], expected: list[dict], k: int) -> float:
    if not expected:
        return 1.0
    top = citations[:k]
    hits = sum(1 for c in top if is_relevant(c, expected))
    # Cap at len(expected) since a single chunk can't satisfy two distinct expected items.
    return min(hits, len(expected)) / len(expected)


def ndcg_at_k(citations: list[dict], expected: list[dict], k: int) -> float:
    if not expected:
        return 1.0
    rels = [1.0 if is_relevant(c, expected) else 0.0 for c in citations[:k]]
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels))
    ideal_count = min(len(expected), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


def main(qa_path: Path | None = None, k: int = 5) -> int:
    qa_path = qa_path or (DATASETS / "qa.jsonl")
    if not qa_path.exists():
        print(f"qa file not found: {qa_path}")
        return 2

    rows: list[dict] = []
    with qa_path.open() as f:
        items = [json.loads(line) for line in f if line.strip()]

    if not items:
        print("qa.jsonl is empty; populate it before running retrieval eval")
        return 2

    for item in items:
        # Resolve doc_set to a single dir if all share a parent; else use first.
        doc_paths = [(DATASETS / d).resolve() for d in item.get("doc_set", [])]
        if not doc_paths:
            rows.append({"query_id": item["query_id"], "error": "no doc_set"})
            continue
        docs_arg = doc_paths[0].parent if len(doc_paths) > 1 else doc_paths[0]

        # We need an audio file to run the pipeline; eval reuses any short clip
        # tagged with this query, falling back to the first listed clip.
        audio_rel = item.get("audio") or _fallback_audio()
        audio = (DATASETS / audio_rel).resolve() if audio_rel else None
        if audio is None or not audio.exists():
            rows.append({"query_id": item["query_id"], "error": "missing audio"})
            continue

        try:
            result = run_pipeline(audio, docs_arg, question=item.get("query"))
        except Exception as e:
            rows.append({"query_id": item["query_id"], "error": str(e)})
            continue

        citations = result.get("citations", [])
        expected = item.get("expected_citations", [])
        rows.append(
            {
                "query_id": item["query_id"],
                "lang": item.get("lang"),
                "recall_at_k": recall_at_k(citations, expected, k),
                "ndcg_at_k": ndcg_at_k(citations, expected, k),
                "stub": all(c.get("score") == 0.0 for c in citations),
            }
        )

    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / f"retrieval_{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps({"k": k, "rows": rows}, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")

    real = [r for r in rows if "recall_at_k" in r and not r.get("stub")]
    if real:
        avg_r = sum(r["recall_at_k"] for r in real) / len(real)
        avg_n = sum(r["ndcg_at_k"] for r in real) / len(real)
        print(f"avg recall@{k}: {avg_r:.3f}, avg nDCG@{k}: {avg_n:.3f} over {len(real)} queries")
    else:
        print("(no non-stub rows; retrieval is still stubbed in sidecar)")
    return 0


def _fallback_audio() -> str | None:
    manifest = DATASETS / "manifest.json"
    if not manifest.exists():
        return None
    m = json.loads(manifest.read_text())
    clips = m.get("audio_clips", [])
    return clips[0]["audio"] if clips else None


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--qa", type=Path, default=None)
    p.add_argument("-k", type=int, default=5)
    args = p.parse_args()
    raise SystemExit(main(args.qa, args.k))
