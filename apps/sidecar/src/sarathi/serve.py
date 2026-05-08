"""Streaming `serve` mode — long-running NDJSON event loop.

Wire protocol
=============

Input (stdin, line-delimited JSON):

    {"type": "audio", "pcm_b64": "<base64 of int16 mono 16kHz PCM>"}
    {"type": "ingest", "path": "<absolute path to file or directory>"}
    {"type": "question", "text": "<explicit question to answer>"}
    {"type": "session", "action": "start" | "end", "id": "<session_id>",
     "title": "<optional>"}
    {"type": "shutdown"}

Output (stdout, line-delimited JSON):

    {"type": "ready", "version": "...", "stub_stages": [...]}
    {"type": "utterance", "text": "...", "start_s": ..., "end_s": ...,
     "lang": "...", "session_id": "..."}
    {"type": "question", "tier": "heuristic" | "llm",
     "text": "...", "confidence": ..., "query": "..."}
    {"type": "reference", "trigger": "question" | "proactive",
     "query": "...", "citations": [...]}
    {"type": "answer", "text": "...", "citations": [...]}
    {"type": "ingested", "doc_count": int, "chunk_count": int}
    {"type": "error", "message": "..."}

Design notes
------------

- One command per stdin line; one event per stdout line.
- Audio is the high-volume channel. Base64 over JSON is inefficient
  (~33% overhead); at 16kHz mono int16 that's ~32 KB/s of PCM →
  ~43 KB/s of base64. Trivial. Switching to a separate FIFO/socket is
  a v1 optimization if we ever care.
- Stages that need ML deps degrade gracefully: missing whisper → no
  utterances; missing LLM → no proactive references. Errors surface as
  a single `error` event, never crash the process.
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from sarathi import __version__
from sarathi.config import Config
from sarathi.qdetect.heuristic import detect_question_heuristic
from sarathi.qdetect.rolling import RollingWindow, Utterance


# Stdout is shared between the main thread (command handler) and the vacuum
# background thread. NDJSON writes must be atomic per-line.
_STDOUT_LOCK = threading.Lock()


def _emit(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with _STDOUT_LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


def _err(msg: str, **extra) -> None:
    _emit({"type": "error", "message": msg, **extra})


# ---------------------------------------------------------------------------#
# Lazy / optional pieces — wrapped so `serve` boots even without [ml] extras.
# ---------------------------------------------------------------------------#


def _try_make_diarizer(cfg: Config):
    """Return a Diarizer or None. Disabled by config or missing deps both
    return None silently — diarization is opt-in."""
    diar_cfg = cfg.section("diarize") if hasattr(cfg, "section") else {}
    if not diar_cfg.get("enabled", False):
        return None
    try:
        from sarathi.asr.diarize import Diarizer
    except RuntimeError:
        return None
    try:
        return Diarizer(
            model=diar_cfg.get("model", "pyannote/speaker-diarization-3.1"),
            min_duration_s=diar_cfg.get("min_duration_s", 1.0),
        )
    except RuntimeError:
        return None


def _try_make_transcriber(cfg: Config):
    try:
        from sarathi.asr.streaming import StreamingTranscriber
        from sarathi.asr.vad import VadConfig
    except RuntimeError as e:
        return None, str(e)

    asr = cfg.section("asr")
    vad = cfg.section("vad")
    diarizer = _try_make_diarizer(cfg)
    try:
        t = StreamingTranscriber(
            vad=VadConfig(
                threshold=0.5,
                min_silence_ms=vad.get("min_silence_ms", 400),
                max_segment_s=vad.get("max_segment_s", 28),
                pad_ms=int(vad.get("overlap_s", 1.5) * 1000 / 2),  # half each side
            ),
            model=asr.get("model", "large-v3"),
            compute_type=asr.get("compute_type", "int8_float16"),
            language=(asr.get("language") or None),
            no_speech_threshold=asr.get("no_speech_threshold", 0.6),
            condition_on_previous_text=asr.get("condition_on_previous_text", False),
            diarizer=diarizer,
        )
    except RuntimeError as e:
        return None, str(e)
    return t, None


def _try_retrieve_for_query(query: str, cfg: Config) -> list[dict] | None:
    """Run hybrid retrieval against the existing LanceDB store; return citations
    formatted for downstream events. Returns None if anything is missing."""
    try:
        from sarathi.embed.bge_m3 import embed_query
        from sarathi.retrieve.hybrid import hybrid_search
        from sarathi.retrieve.lance_store import LanceStore
        from sarathi.retrieve.rerank import rerank
    except RuntimeError:
        return None

    paths = cfg.section("paths")
    db_path = cfg.resolve_path(paths.get("data_dir", "data")) / "lance"
    if not db_path.exists():
        return None
    store = LanceStore(db_path)
    if store.count() == 0:
        return None

    embed_cfg = cfg.section("embed")
    qcfg = cfg.section("retrieve")
    rcfg = cfg.section("rerank")

    try:
        q = embed_query(query, model=embed_cfg.get("model", "BAAI/bge-m3"))
        fused = hybrid_search(
            store,
            query_dense=q.dense,
            query_sparse=q.sparse,
            dense_k=qcfg.get("dense_k", 30),
            sparse_k=qcfg.get("sparse_k", 30),
            rrf_k=qcfg.get("rrf_k", 60),
            final_k=rcfg.get("top_k_in", 20),
        )
    except RuntimeError:
        return None

    rows = store.get_by_ids([h.chunk_id for h in fused])
    by_id = {r["id"]: r for r in rows}

    if rcfg.get("enabled", True) and rows:
        ranked = rerank(
            query,
            [(h.chunk_id, by_id[h.chunk_id]["text"]) for h in fused if h.chunk_id in by_id],
            model=rcfg.get("model", "BAAI/bge-reranker-v2-m3"),
            top_k=rcfg.get("top_k_out", 5),
        )
        ordered = [(h.chunk_id, h.score) for h in ranked]
    else:
        ordered = [(h.chunk_id, h.score) for h in fused[: qcfg.get("final_k", 8)]]

    out = []
    for cid, score in ordered:
        r = by_id.get(cid)
        if not r:
            continue
        out.append(
            {
                "chunk_id": cid,
                "text": r["text"],
                "lang": r.get("lang") or None,
                "source": r.get("source"),
                "page": r.get("page"),
                "score": score,
            }
        )
    return out


def _try_answer(*, question: str, transcript: str, citations: list[dict], cfg: Config) -> dict:
    if not citations:
        return {
            "text": "I don't have enough information in the provided documents to answer that.",
            "citations": [],
        }
    try:
        from sarathi.llm.mlx_runner import generate
        from sarathi.llm.prompt import SYSTEM as LLM_SYSTEM
        from sarathi.llm.prompt import ContextChunk, build_user_message
    except RuntimeError as e:
        return {"text": "", "citations": citations, "stub": True, "reason": str(e)}

    ctx = [
        ContextChunk(
            chunk_id=f"c{i + 1}",
            text=c["text"],
            source=c.get("source") or "",
            page=c.get("page"),
            lang=c.get("lang"),
        )
        for i, c in enumerate(citations)
    ]
    user = build_user_message(question=question, transcript=transcript, chunks=ctx)
    llm = cfg.section("llm")
    try:
        out = generate(
            system=LLM_SYSTEM,
            user=user,
            model=llm.get("model", "mlx-community/Qwen2.5-14B-Instruct-4bit"),
            max_new_tokens=llm.get("max_new_tokens", 512),
            temperature=llm.get("temperature", 0.2),
        )
    except RuntimeError as e:
        return {"text": "", "citations": citations, "stub": True, "reason": str(e)}

    return {"text": out.text, "citations": citations, "model": out.model}


# ---------------------------------------------------------------------------#
# Server state
# ---------------------------------------------------------------------------#


@dataclass
class ServeState:
    cfg: Config
    rolling: RollingWindow
    session_id: str | None = None
    last_proactive_at: float = 0.0
    proactive_every_n: int = 4    # utterances
    proactive_min_interval_s: float = 20.0
    utterances_since_proactive: int = 0


def _handle_utterances(state: ServeState, segs: Iterable, *, store) -> None:
    for seg in segs:
        if not seg.text:
            continue

        u = Utterance(
            text=seg.text, start_s=seg.start_s, end_s=seg.end_s, lang=seg.language
        )
        state.rolling.add(u)

        speaker_id = getattr(seg, "speaker_id", None)

        # Persist to SQLite if store is available.
        if store is not None and state.session_id:
            try:
                store.append_transcript(
                    session_id=state.session_id,
                    text=seg.text,
                    lang=seg.language,
                    speaker_id=speaker_id,
                    start_s=seg.start_s,
                    end_s=seg.end_s,
                )
            except Exception as e:
                _err(f"transcript persist failed: {e}")

        _emit(
            {
                "type": "utterance",
                "text": seg.text,
                "start_s": seg.start_s,
                "end_s": seg.end_s,
                "lang": seg.language,
                "speaker_id": speaker_id,
                "session_id": state.session_id,
            }
        )

        # Tier-1 question detection on the new utterance.
        h = detect_question_heuristic(seg.text, lang=seg.language)
        if h.is_question and h.confidence >= 0.6:
            _emit(
                {
                    "type": "question",
                    "tier": "heuristic",
                    "text": seg.text,
                    "confidence": h.confidence,
                    "reason": h.reason,
                    "query": seg.text,
                }
            )
            _trigger_retrieve_and_answer(
                state, query=seg.text, question=seg.text, trigger="question"
            )

        # Proactive references every N utterances (rate-limited).
        state.utterances_since_proactive += 1
        now = time.time()
        if (
            state.utterances_since_proactive >= state.proactive_every_n
            and (now - state.last_proactive_at) >= state.proactive_min_interval_s
        ):
            state.utterances_since_proactive = 0
            state.last_proactive_at = now
            window_text = state.rolling.text()
            if window_text:
                citations = _try_retrieve_for_query(window_text, state.cfg)
                if citations:
                    _emit(
                        {
                            "type": "reference",
                            "trigger": "proactive",
                            "query": window_text[-200:],
                            "citations": citations,
                        }
                    )


def _trigger_retrieve_and_answer(
    state: ServeState, *, query: str, question: str, trigger: str
) -> None:
    citations = _try_retrieve_for_query(query, state.cfg) or []
    _emit(
        {
            "type": "reference",
            "trigger": trigger,
            "query": query,
            "citations": citations,
        }
    )
    answer = _try_answer(
        question=question,
        transcript=state.rolling.text(),
        citations=citations,
        cfg=state.cfg,
    )
    _emit({"type": "answer", **answer})


# ---------------------------------------------------------------------------#
# Audio command processing
# ---------------------------------------------------------------------------#


def _decode_pcm(b64: str) -> np.ndarray:
    raw = base64.b64decode(b64)
    return np.frombuffer(raw, dtype=np.int16)


@contextmanager
def _open_store(cfg: Config):
    try:
        from sarathi.store.sqlite import Store
    except Exception:
        yield None
        return

    paths = cfg.section("paths")
    db_path = cfg.resolve_path(paths.get("data_dir", "data")) / "metadata.db"
    store = Store(db_path)
    try:
        yield store
    finally:
        store.close()


def _ingest_path_event(path: Path, cfg: Config, store) -> None:
    """Re-use the file-based pipeline's ingest+embed+index step."""
    try:
        from sarathi.pipeline import _try_embed_and_index, ingest_docs
    except Exception as e:
        _err(f"ingest unavailable: {e}")
        return
    try:
        chunks, doc_meta = ingest_docs(path, cfg)
        ok, reason = _try_embed_and_index(chunks, doc_meta, cfg, store)
        _emit(
            {
                "type": "ingested",
                "doc_count": len(doc_meta),
                "chunk_count": len(chunks),
                "indexed": ok,
                "reason": reason,
            }
        )
    except Exception as e:
        _err(f"ingest failed: {e}")


# ---------------------------------------------------------------------------#
# Retention vacuum
# ---------------------------------------------------------------------------#


def _start_vacuum_thread(
    store, retention_days: int, interval_s: float, stop_event: threading.Event
) -> threading.Thread:
    """Background thread: every `interval_s`, delete transcripts older than
    `retention_days`. Emits a `vacuumed` event with the deleted row count.

    A separate SQLite connection is created inside the thread because
    sqlite3 connections are not safe to share across threads by default.
    """

    def loop() -> None:
        # Run a "boot vacuum" first — useful when the app has been closed for
        # longer than the retention window and starts up with stale rows.
        if not stop_event.is_set():
            _vacuum_once(store, retention_days)

        while not stop_event.wait(interval_s):
            _vacuum_once(store, retention_days)

    t = threading.Thread(target=loop, name="sarathi-vacuum", daemon=True)
    t.start()
    return t


def _vacuum_once(store, retention_days: int) -> None:
    if store is None:
        return
    try:
        deleted = store.vacuum_old(retention_days)
        if deleted > 0:
            _emit(
                {
                    "type": "vacuumed",
                    "deleted_transcripts": int(deleted),
                    "retention_days": int(retention_days),
                }
            )
    except Exception as e:
        _err(f"vacuum failed: {e}")


# ---------------------------------------------------------------------------#
# Main loop
# ---------------------------------------------------------------------------#


def serve_loop(cfg: Config) -> int:
    transcriber, asr_err = _try_make_transcriber(cfg)
    stub_stages: list[str] = []
    if transcriber is None:
        stub_stages.append(f"asr: {asr_err}")

    state = ServeState(cfg=cfg, rolling=RollingWindow(horizon_s=180.0))

    _emit(
        {
            "type": "ready",
            "version": __version__,
            "stub_stages": stub_stages,
        }
    )

    retention_days = int(cfg.section("retention").get("transcripts_days", 15))
    # Run vacuum every 6 hours during a long-lived session. For shorter
    # sessions the boot vacuum on each `serve` start handles staleness.
    vacuum_interval_s = float(
        cfg.section("retention").get("vacuum_interval_s", 6 * 60 * 60)
    )
    stop_vacuum = threading.Event()

    with _open_store(cfg) as store:
        # SQLite connections aren't shareable across threads — the vacuum
        # thread opens its own using the same db path.
        from sarathi.store.sqlite import Store as _Store

        if store is not None:
            paths = cfg.section("paths")
            db_path = cfg.resolve_path(paths.get("data_dir", "data")) / "metadata.db"
            vacuum_store = _Store(db_path)
            _start_vacuum_thread(
                vacuum_store, retention_days, vacuum_interval_s, stop_vacuum
            )
        else:
            vacuum_store = None

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError as e:
                _err(f"bad json: {e}")
                continue

            ctype = cmd.get("type")
            try:
                if ctype == "shutdown":
                    if transcriber is not None:
                        _handle_utterances(state, transcriber.flush(), store=store)
                    if state.session_id and store is not None:
                        store.end_session(state.session_id)
                    stop_vacuum.set()
                    if vacuum_store is not None:
                        try:
                            vacuum_store.close()
                        except Exception:
                            pass
                    return 0

                if ctype == "audio":
                    if transcriber is None:
                        _err("asr unavailable", reason=asr_err)
                        continue
                    pcm = _decode_pcm(cmd["pcm_b64"])
                    _handle_utterances(state, transcriber.feed(pcm), store=store)

                elif ctype == "ingest":
                    p = Path(cmd["path"])
                    if not p.exists():
                        _err(f"path not found: {p}")
                        continue
                    _ingest_path_event(p, cfg, store)

                elif ctype == "question":
                    q = cmd.get("text") or ""
                    if not q.strip():
                        _err("empty question")
                        continue
                    _trigger_retrieve_and_answer(
                        state, query=q, question=q, trigger="question"
                    )

                elif ctype == "session":
                    action = cmd.get("action")
                    sid = cmd.get("id")
                    if action == "start":
                        state.session_id = sid
                        if store is not None and sid:
                            store.start_session(sid, title=cmd.get("title"))
                    elif action == "end":
                        if transcriber is not None:
                            _handle_utterances(state, transcriber.flush(), store=store)
                        if state.session_id and store is not None:
                            store.end_session(state.session_id)
                        state.session_id = None
                        state.rolling.clear()
                    else:
                        _err(f"unknown session action: {action}")

                else:
                    _err(f"unknown command type: {ctype}")

            except Exception as e:
                _err(f"{ctype}: {e}")

    return 0
