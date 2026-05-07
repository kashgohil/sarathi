"""End-to-end pipeline orchestrator.

Stages:
    1. Ingest docs   → Blocks (per-page, lang-tagged)
    2. Normalize     → NFC + Indic normalization
    3. Chunk         → sentence-anchored, token-counted Chunks
    4. Embed         → BGE-M3 dense + sparse
    5. Index         → upsert into LanceDB + SQLite metadata
    6. Transcribe    → faster-whisper file mode
    7. Retrieve      → hybrid (dense+sparse) RRF + rerank
    8. Answer        → MLX LLM with citation prompt

Each stage is wrapped in a try/except that catches `RuntimeError` from
the lazy ML imports — if the `[ml]` extras aren't installed, the stage
returns a stub result and the pipeline continues. This lets the eval
harness exercise the JSON shape with no GPU/MLX setup.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sarathi.config import Config
from sarathi.ingest.lang_id import detect_lang
from sarathi.ingest.pdf import extract_pdf
from sarathi.ingest.types import Block
from sarathi.llm.prompt import SYSTEM as LLM_SYSTEM
from sarathi.llm.prompt import ContextChunk, build_user_message
from sarathi.store.sqlite import Store, doc_id_for, file_hash
from sarathi.textproc.chunk import Chunk, ChunkConfig, chunk_text
from sarathi.textproc.normalize import normalize


@dataclass
class PipelineResult:
    transcript: dict[str, Any]
    citations: list[dict[str, Any]]
    answer: dict[str, Any]
    chunk_count: int
    stub_stages: list[str] = field(default_factory=list)


def _ingest_one(path: Path, *, fasttext_model: str | None) -> Iterable[Block]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        for b in extract_pdf(path):
            if b.text:
                b.lang = detect_lang(b.text, fasttext_model=fasttext_model)
            yield b
    elif suffix in {".txt", ".md"}:
        text = path.read_text(encoding="utf-8")
        for i, para in enumerate(text.split("\n\n")):
            if not para.strip():
                continue
            yield Block(
                text=para.strip(),
                page=1,
                source=str(path.resolve()),
                block_index=i,
                lang=detect_lang(para, fasttext_model=fasttext_model),
            )


def _resolve_inputs(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(
        p
        for p in target.rglob("*")
        if p.is_file() and p.suffix.lower() in {".pdf", ".txt", ".md"}
    )


def _chunk_cfg(cfg: Config) -> ChunkConfig:
    s = cfg.section("chunk")
    return ChunkConfig(
        target_tokens=s.get("target_tokens", 400),
        max_tokens=s.get("max_tokens", 512),
        overlap_tokens=s.get("overlap_tokens", 50),
        overlap_sentences=s.get("overlap_sentences", 1),
        embed_tokenizer=s.get("embed_tokenizer", "BAAI/bge-m3"),
    )


def ingest_docs(target: Path, cfg: Config) -> tuple[list[Chunk], list[dict]]:
    """Ingest + chunk all docs under `target`. Returns (chunks, doc_meta)."""
    chunk_cfg = _chunk_cfg(cfg)
    fasttext_model = cfg.section("lang_id").get("model_path")

    all_chunks: list[Chunk] = []
    doc_meta: list[dict] = []

    for path in _resolve_inputs(target):
        blocks = list(_ingest_one(path, fasttext_model=fasttext_model))
        if not blocks:
            continue
        # Pick a doc-level lang as the modal block lang.
        langs = [b.lang for b in blocks if b.lang]
        primary = max(set(langs), key=langs.count) if langs else None

        doc_meta.append(
            {
                "source": str(path.resolve()),
                "title": path.stem,
                "lang_primary": primary,
                "page_count": max((b.page for b in blocks), default=0),
                "content_hash": file_hash(path) if path.is_file() else "",
            }
        )

        # Chunk each block; carry source/page metadata onto each chunk.
        for b in blocks:
            text = normalize(b.text, lang=b.lang)
            if not text:
                continue
            for c in chunk_text(
                text,
                lang=b.lang,
                config=chunk_cfg,
                metadata={"source": b.source, "page": b.page, "is_ocr": b.is_ocr},
            ):
                all_chunks.append(c)

    return all_chunks, doc_meta


def _try_embed_and_index(
    chunks: list[Chunk], doc_meta: list[dict], cfg: Config, store: Store
) -> tuple[bool, str | None]:
    """Embed chunks with BGE-M3 and upsert into LanceDB + SQLite.

    Returns (succeeded, reason). On failure, the pipeline still proceeds
    using in-memory chunks for retrieval (degraded but functional path).
    """
    try:
        from sarathi.embed.bge_m3 import embed
        from sarathi.retrieve.lance_store import LanceStore, StoredChunk
    except RuntimeError as e:
        return False, str(e)

    if not chunks:
        return True, None

    # Persist doc rows.
    doc_ids: dict[str, str] = {}
    for dm in doc_meta:
        did = store.upsert_doc(
            source=dm["source"],
            title=dm["title"],
            content_hash=dm["content_hash"],
            page_count=dm["page_count"],
            lang_primary=dm["lang_primary"],
        )
        doc_ids[dm["source"]] = did

    # Embed.
    embed_cfg = cfg.section("embed")
    try:
        outputs = embed(
            [c.text for c in chunks],
            model=embed_cfg.get("model", "BAAI/bge-m3"),
            return_sparse=bool(embed_cfg.get("hybrid", True)),
        )
    except RuntimeError as e:
        return False, str(e)

    # Build StoredChunk rows.
    db_path = cfg.resolve_path(cfg.section("paths").get("data_dir", "data"))
    lance = LanceStore(db_path / "lance", dim=len(outputs[0].dense) if outputs else 1024)

    stored: list[StoredChunk] = []
    sqlite_rows: list[dict] = []
    for idx, (c, out) in enumerate(zip(chunks, outputs, strict=True)):
        source = c.metadata.get("source", "")
        did = doc_ids.get(source) or doc_id_for(source)
        cid = f"{did}:{idx}"
        stored.append(
            StoredChunk(
                id=cid,
                doc_id=did,
                source=source,
                page=int(c.metadata.get("page", 0) or 0),
                lang=c.lang,
                text=c.text,
                vector=out.dense,
                sparse=out.sparse,
                metadata=c.metadata,
            )
        )
        sqlite_rows.append(
            {
                "id": cid,
                "doc_id": did,
                "chunk_idx": idx,
                "page": int(c.metadata.get("page", 0) or 0),
                "lang": c.lang,
                "token_count": c.token_count,
                "text": c.text,
            }
        )

    lance.upsert(stored)
    store.insert_chunks(sqlite_rows)
    return True, None


def _try_transcribe(audio: Path, cfg: Config) -> tuple[dict, bool]:
    try:
        from sarathi.asr.whisper import asr_config_from, transcribe_file
    except RuntimeError as e:
        return {"text": "", "segments": [], "language": None, "stub": True, "reason": str(e)}, True

    opts = asr_config_from(cfg)
    try:
        t = transcribe_file(audio, **opts)
    except RuntimeError as e:
        return {"text": "", "segments": [], "language": None, "stub": True, "reason": str(e)}, True

    return (
        {
            "text": t.text,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text, "language": s.language}
                for s in t.segments
            ],
            "language": t.language,
            "duration": t.duration,
            "stub": False,
        },
        False,
    )


def _try_retrieve(
    chunks: list[Chunk], cfg: Config, *, query: str
) -> tuple[list[dict], bool]:
    """Hybrid retrieve via LanceDB. Falls back to first-N in-memory chunks
    if the ML stack isn't available."""
    try:
        from sarathi.embed.bge_m3 import embed_query
        from sarathi.retrieve.hybrid import hybrid_search
        from sarathi.retrieve.lance_store import LanceStore
        from sarathi.retrieve.rerank import rerank
    except RuntimeError:
        # In-memory fallback (no embeddings, no scores).
        return _stub_citations(chunks), True

    paths = cfg.section("paths")
    db_path = cfg.resolve_path(paths.get("data_dir", "data")) / "lance"
    if not db_path.exists():
        return _stub_citations(chunks), True

    store = LanceStore(db_path)
    if store.count() == 0:
        return _stub_citations(chunks), True

    qcfg = cfg.section("retrieve")
    rcfg = cfg.section("rerank")
    embed_cfg = cfg.section("embed")

    q = embed_query(query, model=embed_cfg.get("model", "BAAI/bge-m3"))
    fused = hybrid_search(
        store,
        query_dense=q.dense,
        query_sparse=q.sparse,
        dense_k=qcfg.get("dense_k", 30),
        sparse_k=qcfg.get("sparse_k", 30),
        rrf_k=qcfg.get("rrf_k", 60),
        final_k=rcfg.get("top_k_in", 20) if rcfg.get("enabled", True) else qcfg.get("final_k", 8),
    )

    # Hydrate full rows for rerank input.
    rows = store.get_by_ids([h.chunk_id for h in fused])
    by_id = {r["id"]: r for r in rows}

    if rcfg.get("enabled", True) and rows:
        reranked = rerank(
            query,
            [(h.chunk_id, by_id[h.chunk_id]["text"]) for h in fused if h.chunk_id in by_id],
            model=rcfg.get("model", "BAAI/bge-reranker-v2-m3"),
            top_k=rcfg.get("top_k_out", 5),
        )
        ordered_ids = [h.chunk_id for h in reranked]
        scores = {h.chunk_id: h.score for h in reranked}
    else:
        ordered_ids = [h.chunk_id for h in fused[: qcfg.get("final_k", 8)]]
        scores = {h.chunk_id: h.score for h in fused}

    citations = []
    for cid in ordered_ids:
        r = by_id.get(cid)
        if not r:
            continue
        citations.append(
            {
                "chunk_id": cid,
                "text": r["text"],
                "lang": r.get("lang") or None,
                "source": r.get("source"),
                "page": r.get("page"),
                "score": scores.get(cid, 0.0),
            }
        )
    return citations, False


def _stub_citations(chunks: list[Chunk]) -> list[dict]:
    return [
        {
            "chunk_id": f"stub:{i}",
            "text": c.text,
            "lang": c.lang,
            "source": c.metadata.get("source"),
            "page": c.metadata.get("page"),
            "score": 0.0,
        }
        for i, c in enumerate(chunks[:5])
    ]


def _try_answer(
    *, question: str, transcript: str | None, citations: list[dict], cfg: Config
) -> tuple[dict, bool]:
    if not question or not citations:
        return (
            {
                "text": "I don't have enough information in the provided documents to answer that.",
                "stub": False,
                "reason": "no question or no citations",
            },
            False,
        )

    try:
        from sarathi.llm.mlx_runner import generate
    except RuntimeError as e:
        return {"text": "", "stub": True, "reason": str(e)}, True

    llm_cfg = cfg.section("llm")
    ctx_chunks = [
        ContextChunk(
            chunk_id=f"c{i + 1}",
            text=c["text"],
            source=c.get("source") or "",
            page=c.get("page"),
            lang=c.get("lang"),
        )
        for i, c in enumerate(citations)
    ]
    user = build_user_message(question=question, transcript=transcript, chunks=ctx_chunks)

    try:
        result = generate(
            system=LLM_SYSTEM,
            user=user,
            model=llm_cfg.get("model", "mlx-community/Qwen2.5-14B-Instruct-4bit"),
            max_new_tokens=llm_cfg.get("max_new_tokens", 512),
            temperature=llm_cfg.get("temperature", 0.2),
        )
    except RuntimeError as e:
        return {"text": "", "stub": True, "reason": str(e)}, True

    return (
        {
            "text": result.text,
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "output_tokens": result.output_tokens,
            "stub": False,
        },
        False,
    )


def run(
    *,
    audio: Path,
    docs: Path,
    cfg: Config,
    question: str | None = None,
) -> PipelineResult:
    stub_stages: list[str] = []

    # 1-3. Ingest, normalize, chunk.
    chunks, doc_meta = ingest_docs(docs, cfg)

    # 4-5. Embed + index.
    db_path = cfg.resolve_path(cfg.section("paths").get("data_dir", "data"))
    store = Store(db_path / "metadata.db")
    indexed, reason = _try_embed_and_index(chunks, doc_meta, cfg, store)
    if not indexed:
        stub_stages.append(f"embed/index: {reason}")

    # 6. Transcribe.
    transcript, asr_stub = _try_transcribe(audio, cfg)
    if asr_stub:
        stub_stages.append(f"asr: {transcript.get('reason', '')}")

    # 7. Retrieve. If no question provided, fall back to using the transcript
    # as the query — useful for proactive references during a live session.
    query = question or transcript.get("text", "") or ""
    citations, retr_stub = _try_retrieve(chunks, cfg, query=query)
    if retr_stub:
        stub_stages.append("retrieve: in-memory fallback")

    # 8. Answer.
    answer, llm_stub = _try_answer(
        question=question or "",
        transcript=transcript.get("text") if transcript.get("text") else None,
        citations=citations,
        cfg=cfg,
    )
    if llm_stub:
        stub_stages.append(f"llm: {answer.get('reason', '')}")

    return PipelineResult(
        transcript=transcript,
        citations=citations,
        answer=answer,
        chunk_count=len(chunks),
        stub_stages=stub_stages,
    )
