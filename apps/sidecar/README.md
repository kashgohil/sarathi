# Sidecar

Python ML process. Runs ASR, VAD, OCR, embeddings, retrieval, and the local LLM. Communicates with the desktop app over stdio (NDJSON).

## Layout

```
src/sarathi/
  cli.py            Typer entry — `sarathi {ingest,chunk,run,serve}`
  config.py         TOML config loader
  pipeline.py       File-based orchestrator (used by `run`)
  serve.py          Streaming NDJSON event loop (used by `serve`)
  textproc/         Gujarati-aware normalize + sentence-split + chunk
  ingest/           PDF (pymupdf), OCR (PaddleOCR), language ID (script + fasttext)
  asr/              vad.py (silero), whisper.py (file), streaming.py (live)
  embed/            BGE-M3 hybrid (dense + sparse)
  retrieve/         LanceDB + RRF + bge-reranker-v2-m3
  llm/              MLX runner + system prompt
  qdetect/          rolling window, heuristic + LLM tiers
  store/            SQLite for transcripts + retention
config/defaults.toml
tests/
```

## Setup

Uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
cd apps/sidecar
uv sync                  # core deps only — fast, no ML downloads
uv sync --extra ml       # whisper, silero, bge-m3, mlx-lm, paddle (~15GB on first run)
uv sync --extra dev      # pytest, ruff, mypy
```

## Subcommands

```bash
# 1. Inspect chunking on Gujarati prose:
uv run sarathi chunk "નમસ્તે દુનિયા। આ સારથી છે।" --lang gu

# 2. Ingest a PDF (text-layer; OCR needs [ml] extras):
uv run sarathi ingest path/to/doc.pdf

# 3. One-shot end-to-end on a recorded clip:
uv run sarathi run --audio sample.wav --docs ./docs/

# 4. Streaming server (read NDJSON commands from stdin, emit events to stdout):
uv run sarathi serve
```

## `serve` wire protocol

All messages are line-delimited JSON.

**Commands → stdin:**

| `type` | Fields | Effect |
|---|---|---|
| `audio` | `pcm_b64` (base64 of 16 kHz mono int16 PCM) | Feed audio to VAD/ASR |
| `ingest` | `path` (file or dir) | Ingest, embed, index |
| `question` | `text` | Force a Q&A turn |
| `session` | `action: start\|end`, `id`, `title?` | Session lifecycle |
| `shutdown` | — | Flush and exit |

**Events ← stdout:**

| `type` | Notes |
|---|---|
| `ready` | First event; includes `stub_stages` listing degraded components |
| `utterance` | Final transcript chunk for one VAD utterance |
| `question` | Heuristic or LLM-tier detection |
| `reference` | Retrieved citations (proactive or question-triggered) |
| `answer` | LLM answer + citations |
| `ingested` | Ingest summary |
| `error` | Recoverable error (process keeps running) |

## Quality gates

```bash
uv run pytest                    # textproc, lang_id, hybrid, sqlite, qdetect, rolling
uv run ruff check .
uv run mypy src
```

Most tests run with the core deps only — only the heavier integration tests (whisper, BGE-M3, MLX) require the `[ml]` extras.

## Status

- M0: ✅ eval scaffolding + harness (`eval/`)
- M1: ✅ file-based pipeline (real impls behind `[ml]` extras; stubs without)
- M2: ✅ streaming ASR + VAD + question detection + `serve` mode
- M3+: see `docs/architecture.md`
