"""End-to-end eval: LLM-as-judge over (audio + docs → expected answer) triples.

For each row in qa.jsonl, runs the sidecar `run` command and asks an
external judge (Anthropic API) to score the produced answer for
faithfulness and helpfulness against the expected answer.

The judge is the only cloud touchpoint in the project — it is used for
**eval only**, never at runtime. If you want a fully-local eval, swap
the judge for a local LLM (worse signal, no API key required).

Env: ANTHROPIC_API_KEY required to run the judge.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from textwrap import dedent

from harness.sidecar_client import run_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS = REPO_ROOT / "eval" / "datasets"
RESULTS = REPO_ROOT / "eval" / "results"

JUDGE_MODEL = os.environ.get("SARATHI_EVAL_JUDGE", "claude-opus-4-7")

JUDGE_SYSTEM = dedent(
    """
    You are an evaluator for a RAG question-answering system.
    Score the predicted answer on:
      - faithfulness (0-3): is every claim supported by the cited context?
      - helpfulness (0-3): does the answer address the user's question?
      - citation_quality (0-3): are citations specific and relevant?
    Reply with strict JSON: {"faithfulness": int, "helpfulness": int, "citation_quality": int, "notes": str}.
    """
).strip()


def judge(question: str, expected: str, predicted: dict) -> dict:
    try:
        from anthropic import Anthropic
    except ImportError:
        return {"error": "anthropic package not installed"}
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {"error": "ANTHROPIC_API_KEY not set"}

    client = Anthropic()
    user = json.dumps(
        {
            "question": question,
            "expected_answer": expected,
            "predicted_answer": predicted.get("answer", {}).get("text", ""),
            "predicted_citations": [
                {"text": c.get("text"), "source": c.get("source"), "page": c.get("page")}
                for c in predicted.get("citations", [])
            ],
        },
        ensure_ascii=False,
    )

    msg = client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=400,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in msg.content if hasattr(b, "text"))
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": "judge_non_json", "raw": text}


def main(qa_path: Path | None = None, skip_judge: bool = False) -> int:
    qa_path = qa_path or (DATASETS / "qa.jsonl")
    if not qa_path.exists():
        print(f"qa file not found: {qa_path}")
        return 2

    items = [json.loads(line) for line in qa_path.read_text().splitlines() if line.strip()]
    if not items:
        print("qa.jsonl is empty")
        return 2

    rows: list[dict] = []
    for item in items:
        doc_paths = [(DATASETS / d).resolve() for d in item.get("doc_set", [])]
        if not doc_paths:
            rows.append({"query_id": item["query_id"], "error": "no doc_set"})
            continue
        docs_arg = doc_paths[0].parent if len(doc_paths) > 1 else doc_paths[0]

        audio_rel = item.get("audio")
        audio = (DATASETS / audio_rel).resolve() if audio_rel else None
        if audio is None or not audio.exists():
            rows.append({"query_id": item["query_id"], "error": "missing audio"})
            continue

        try:
            result = run_pipeline(audio, docs_arg, question=item.get("query"))
        except Exception as e:
            rows.append({"query_id": item["query_id"], "error": str(e)})
            continue

        scores: dict
        if skip_judge or result.get("answer", {}).get("stub"):
            scores = {"skipped": True}
        else:
            scores = judge(item["query"], item.get("expected_answer", ""), result)

        rows.append(
            {
                "query_id": item["query_id"],
                "scores": scores,
                "predicted": result.get("answer"),
                "expected": item.get("expected_answer"),
            }
        )

    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / f"e2e_{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2))
    print(f"wrote {out_path} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--qa", type=Path, default=None)
    p.add_argument("--skip-judge", action="store_true", help="Run pipeline only; don't call judge.")
    args = p.parse_args()
    raise SystemExit(main(args.qa, args.skip_judge))
