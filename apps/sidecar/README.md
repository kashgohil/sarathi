# Sidecar

Python ML process. Runs ASR, VAD, diarization, OCR, embeddings, retrieval, and the local LLM. Communicates with the desktop app over stdio (NDJSON).

## Layout

```
src/sarathi/
  cli.py            Typer entry — `sarathi {ingest,chunk,run,serve}`
  config.py         TOML config loader
  textproc/         Gujarati-aware normalize + sentence-split + chunk
  ingest/           PDF (pymupdf), OCR (PaddleOCR), language ID (script + fasttext)
  asr/              faster-whisper streaming (M1/M2)
  embed/            BGE-M3 hybrid (dense + sparse)
  retrieve/         LanceDB + RRF + bge-reranker-v2-m3
  llm/              MLX runner (Qwen2.5 / Llama-3.3)
  store/            SQLite for transcripts + retention
config/defaults.toml
tests/
```

## Setup

Uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
cd apps/sidecar
uv sync                  # core deps only — fast, no ML downloads
uv sync --extra ml       # adds whisper, bge-m3, mlx-lm, paddleocr (large)
uv sync --extra dev      # pytest, ruff, mypy
```

## Quick checks

```bash
# Unit tests for textproc + lang_id (no ML deps required for most).
uv run pytest

# Inspect chunking on Gujarati prose:
uv run sarathi chunk "નમસ્તે દુનિયા। આ સારથી છે।" --lang gu

# Ingest a PDF (text layer only; OCR needs [ml] extras):
uv run sarathi ingest path/to/doc.pdf
```

## Status

- M0 / M1 scaffold: `textproc`, `ingest/{pdf,lang_id}`, `cli` complete.
- ASR / embed / retrieve / llm: stubs; real impls land in M1 once `[ml]` extras are configured locally.
- `serve` mode: stub for M2.
