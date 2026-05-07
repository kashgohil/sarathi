# Eval datasets

Content not in repo (gitignored once large) — collect locally and reference from `manifest.json` / `qa.jsonl`.

## Audio (`audio/`)

Goal: 8–12 short clips (15–60s each) covering the realistic input distribution.

Recommended coverage:

| ID prefix             | Description                                           | Min count |
|-----------------------|-------------------------------------------------------|-----------|
| `gu_mono_*`           | Gujarati monologue, single speaker, clean mic         | 2         |
| `en_mono_*`           | English monologue, single speaker, clean mic          | 2         |
| `gu_en_codeswitch_*`  | Mixed Gujarati + English (typical for IT / business)  | 2         |
| `gu_two_speaker_*`    | Two speakers, 1:1 conversation in Gujarati            | 1–2       |
| `system_audio_*`      | Captured Meet/Zoom output (e.g. recorded test call)   | 1–2       |
| `noisy_mic_*`         | Background noise (cafe / fan / typing)                | 1         |

Format: 16kHz mono WAV preferred. Stereo or higher rates are fine — the sidecar will resample. Hand-transcribe each clip into the `reference` field of `manifest.json`.

## Docs (`docs/`)

Goal: 3 representative documents.

- `docs/sample_gu_native.pdf` — Gujarati PDF with a real text layer (not scanned).
- `docs/sample_gu_scanned.pdf` — Gujarati PDF that is image-only (forces OCR).
- `docs/sample_mixed.pdf` — A doc with both Gujarati and English content.

These can be policy docs, FAQ pages, product manuals — whatever resembles what the production user will upload.

## Q/A pairs (`qa.jsonl`)

Goal: 15–25 triples linking an audio clip + doc set to an expected answer.

Each row, one JSON object per line:

```json
{
  "query_id": "kebab-case-id",
  "query": "What is the question? (English or Gujarati)",
  "lang": "en | gu",
  "audio": "audio/<clip>.wav",
  "doc_set": ["docs/<doc>.pdf"],
  "expected_citations": [
    {"source": "docs/<doc>.pdf", "page": 3, "text_contains": "minimal disambiguating snippet"}
  ],
  "expected_answer": "Concise expected answer in English."
}
```

Notes:
- `text_contains` is a substring match — keep it short (3–8 words) and unambiguous.
- A query can have multiple expected citations; `recall@5` and `nDCG@5` are computed over them.
- The `audio` field reuses clips from the audio set. For "doc-only" queries (no audio), pick a short silent or generic clip.
