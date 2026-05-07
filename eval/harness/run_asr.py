"""ASR eval: compute WER per clip against hand-transcribed references.

Reads `eval/datasets/manifest.json` to find audio clips and their
reference transcripts. Calls the sidecar's `run` command on each clip
(with an empty docs dir, since we only care about the transcript here)
and computes WER using `jiwer`.

Output: `eval/results/asr_<timestamp>.json`
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from harness.sidecar_client import run_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASETS = REPO_ROOT / "eval" / "datasets"
RESULTS = REPO_ROOT / "eval" / "results"


def normalize_for_wer(s: str) -> str:
    # Light, language-agnostic: lower, collapse whitespace, drop ASCII punct.
    import re as _re

    s = s.lower().strip()
    s = _re.sub(r"[.,!?;:\"'()]+", " ", s)
    s = _re.sub(r"\s+", " ", s)
    return s


def main(manifest_path: Path | None = None) -> int:
    try:
        import jiwer
    except ImportError:
        print("jiwer is required: pip install jiwer")
        return 2

    manifest_path = manifest_path or (DATASETS / "manifest.json")
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}")
        return 2

    manifest = json.loads(manifest_path.read_text())
    clips = manifest.get("audio_clips", [])
    if not clips:
        print("no audio clips in manifest; populate eval/datasets/manifest.json first")
        return 2

    empty_docs = DATASETS / "empty_docs"
    empty_docs.mkdir(exist_ok=True)

    rows: list[dict] = []
    for clip in clips:
        audio = (DATASETS / clip["audio"]).resolve()
        if not audio.exists():
            print(f"skip: missing audio {audio}")
            continue
        reference = clip.get("reference", "")

        try:
            result = run_pipeline(audio, empty_docs)
        except Exception as e:
            rows.append({"clip_id": clip["id"], "error": str(e)})
            continue

        hyp = result.get("transcript", {}).get("text", "") or ""
        ref_n = normalize_for_wer(reference)
        hyp_n = normalize_for_wer(hyp)

        wer = jiwer.wer(ref_n, hyp_n) if ref_n else None
        rows.append(
            {
                "clip_id": clip["id"],
                "lang": clip.get("lang"),
                "duration_s": clip.get("duration_s"),
                "wer": wer,
                "reference": reference,
                "hypothesis": hyp,
                "stub": result.get("transcript", {}).get("stub", False),
            }
        )

    RESULTS.mkdir(exist_ok=True)
    out_path = RESULTS / f"asr_{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=2))
    print(f"wrote {out_path} ({len(rows)} rows)")

    # Summary stats — only on rows that produced a real (non-stub) hypothesis.
    real = [r for r in rows if r.get("wer") is not None and not r.get("stub")]
    if real:
        avg = sum(r["wer"] for r in real) / len(real)
        print(f"avg WER (non-stub rows): {avg:.3f} over {len(real)} clips")
    else:
        print("(no non-stub rows; ASR is still stubbed in sidecar)")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, default=None)
    args = p.parse_args()
    raise SystemExit(main(args.manifest))
