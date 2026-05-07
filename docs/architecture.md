# Architecture

## High-level

```
┌─────────────────────────────────────────────────────────┐
│ Tauri app (Rust + web UI)                               │
│  - Audio capture (mic + system audio via ScreenCaptureKit)
│  - Live transcript view, references panel, doc upload   │
└──────────────┬──────────────────────────────────────────┘
               │ IPC (stdio / local socket)
┌──────────────▼──────────────────────────────────────────┐
│ Python sidecar                                          │
│  ASR (faster-whisper) → VAD (silero) → Diarize (pyannote)
│  Q-detect → Retrieval (LanceDB) → Rerank → LLM (MLX)    │
│  OCR (PaddleOCR + pymupdf) for ingest                   │
│  SQLite for transcripts (15-day retention)              │
└─────────────────────────────────────────────────────────┘
```

## Decisions

- **Local-first.** All inference on-device. Cloud is a later addition.
- **Output language: English only** (v0). Gujarati citations are surfaced verbatim.
- **Hardware target: M4 MacBook Pro.** MLX as primary inference runtime.
- **Retention: 15 days** for transcripts; doc embeddings persist.
- **No JS workspace.** Each app is independent; revisit if shared code emerges.

## Gujarati text chunking pipeline

1. **Extract** — pymupdf for text-layer PDFs; PaddleOCR for scans/images; per-block language ID via fasttext lid.176.
2. **Normalize** — Unicode NFC, then `IndicNormalizerFactory` for `gu`. Strip stray ZWJ/ZWNJ; preserve grammatical ones.
3. **Sentence segment** — `indic_nlp_library` for Gujarati (handles `।`, `.`, `?`, `!`); pysbd/spaCy for English.
4. **Chunk** — token-counted via the embedding tokenizer (BGE-M3 / XLM-R), 350–450 tokens, hard cap 512, sentence-anchored, ~50-token or 1-sentence overlap. Grapheme-cluster aware (`regex \X`) for any character-level ops.
5. **Enrich** — prepend `doc_title \n section_path` to each chunk; store metadata (doc_id, page, section_path, lang, source_type, ocr_confidence).
6. **Embed** — BGE-M3 hybrid (dense + sparse). Index dense in LanceDB; sparse via BM25 or BGE-M3 sparse weights. Retrieval = RRF over dense + sparse, then optional bge-reranker-v2-m3.

## Live transcript chunking

- Unit = VAD utterance (silero-vad, 300–500ms silence threshold, ~25–30s max segment, 1–2s overlap).
- Whisper config: `condition_on_previous_text=False`, raised `no_speech_threshold` to suppress hallucinations on silence.
- Rolling window of last ~2–3 minutes feeds retrieval. Re-retrieve on (a) detected question, or (b) every N utterances for proactive references.

## Question detection

- Tier 1: cheap heuristics (interrogative markers in EN/GU, `?`, question stems).
- Tier 2: small LLM call every ~30s on the rolling window — "is there an unresolved question or claim worth referencing?"

## Open items

- Diarization in v0 vs later.
- Eval dataset assembly.
- Encrypted-at-rest transcripts (SQLCipher) — one-way decision.
