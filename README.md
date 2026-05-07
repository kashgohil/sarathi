# Sarathi

Local-first live-audio assistant: transcribes calls/meetings, answers questions, and surfaces references from uploaded docs. Multilingual, starting with Gujarati and English.

## Layout

```
apps/
  desktop/   Tauri desktop app (Rust + web frontend)
  sidecar/   Python ML sidecar (ASR, embeddings, RAG, LLM)
  web/       Marketing site (Astro)
eval/        Evaluation harness and datasets
docs/        Design notes and architecture
```

Each app is independent — its own toolchain, lockfile, and build. No workspace coupling until shared code emerges.

## Status

Pre-implementation. Architecture and chunking pipeline decided; v0 scaffolding in progress.
