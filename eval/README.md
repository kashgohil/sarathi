# Eval harness

Compare model choices end-to-end and per-stage.

- `datasets/` — labeled audio, docs, and query/expected-answer triples (gitignored once large)
- `harness/` — runners and metrics

Tracks:
- ASR: WER on Gujarati + English audio (whisper-large-v3 vs large-v3-turbo vs distil-whisper)
- Retrieval: recall@5 / nDCG@10 on labeled (query → chunk) pairs (BGE-M3 vs multilingual-e5; dense vs hybrid; ± reranker)
- End-to-end: LLM-as-judge on (audio + docs → expected answer) triples
