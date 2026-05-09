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
# Setup-check (lookup, no loading)
# ---------------------------------------------------------------------------#


def _check_setup(cfg: Config) -> dict[str, bool]:
    """Cheap filesystem check: are the model files for each capability
    already cached locally? No model loading happens here — we only ask
    the cache whether config.json (or the silero source folder) exists.

    Returns a dict like `{"asr": True, "embed": False, "llm": False}`.
    Used by the desktop Setup screen to mark already-downloaded
    capabilities as `done` instead of showing them as pending.
    """
    return {
        "asr": _check_silero_vad() and _check_whisper(cfg),
        "embed": _check_hf_cache(cfg.section("embed").get("model", "BAAI/bge-m3")),
        "llm": _check_hf_cache(
            cfg.section("llm").get("model", "mlx-community/Qwen2.5-7B-Instruct-4bit")
        ),
    }


def _check_hf_cache(repo_id: str) -> bool:
    """Probe the HuggingFace hub cache for a model. We try `config.json`
    which every HF repo has. Falls back to a directory check by repo
    name if `huggingface_hub` is unavailable."""
    try:
        from huggingface_hub import try_to_load_from_cache  # noqa: PLC0415
        from huggingface_hub.constants import HF_HUB_CACHE  # noqa: PLC0415

        for filename in ("config.json", "model.safetensors.index.json"):
            try:
                p = try_to_load_from_cache(repo_id=repo_id, filename=filename)
            except Exception:
                continue
            if isinstance(p, str) and Path(p).exists():
                return True

        # Last-resort: presence of a snapshot directory under the repo's
        # cache subtree. Some MLX/quant variants don't have config.json.
        cache_dir = (
            Path(HF_HUB_CACHE)
            / f"models--{repo_id.replace('/', '--')}"
            / "snapshots"
        )
        if cache_dir.is_dir() and any(cache_dir.iterdir()):
            return True
        return False
    except ImportError:
        # No huggingface_hub installed — best-effort check via default cache.
        cache_dir = (
            Path.home()
            / ".cache"
            / "huggingface"
            / "hub"
            / f"models--{repo_id.replace('/', '--')}"
        )
        return cache_dir.is_dir()


def _check_whisper(cfg: Config) -> bool:
    """faster-whisper publishes its model weights at
    `Systran/faster-whisper-<name>` on the Hub."""
    name = cfg.section("asr").get("model", "large-v3-turbo")
    return _check_hf_cache(f"Systran/faster-whisper-{name}")


def _check_silero_vad() -> bool:
    """Silero VAD ships via torch.hub, cached at
    `~/.cache/torch/hub/snakers4_silero-vad_master`. Newer
    `silero-vad` pip package vendors weights so this becomes always-true
    once installed; we treat presence of either path as cached."""
    candidates = [
        Path.home() / ".cache" / "torch" / "hub" / "snakers4_silero-vad_master",
    ]
    if any(p.is_dir() for p in candidates):
        return True
    # The pip-installable `silero-vad` package vendors its model file —
    # if the package imports successfully, the weights are bundled.
    try:
        import silero_vad  # noqa: F401, PLC0415

        return True
    except Exception:
        return False


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


# ---------------------------------------------------------------------------#
# Preload (first-run setup)
# ---------------------------------------------------------------------------#


def _preload(cfg: Config, components: list[str]) -> dict[str, bool]:
    """Trigger lazy loads for the requested components. The loaders emit
    `model_loading` / `model_loaded` events themselves, so the frontend
    gets per-component progress for free.

    Failures don't propagate between components — each is wrapped so a
    missing dep or bad download in one doesn't block the others. Every
    failure (whether the warmup raised or returned a falsy value)
    surfaces as a `model_error` event keyed by the capability name, so
    the UI can flip the matching row to error instead of leaving the
    optimistic spinner running.
    """
    results: dict[str, bool] = {}

    def run(capability: str, fn) -> None:
        try:
            fn(cfg)
            results[capability] = True
        except Exception as e:  # noqa: BLE001
            _emit_capability_error(capability, e)
            results[capability] = False

    if "asr" in components:
        run("asr", _warmup_asr)
    if "embed" in components:
        run("embed", _warmup_embed)
    if "llm" in components:
        run("llm", _warmup_llm)
    return results


def _emit_capability_error(capability: str, err: Exception) -> None:
    """Surface a warmup failure on the matching capability row.

    We translate a few common failure modes into actionable messages —
    the most frequent one in dev is "[ml] extras aren't installed", which
    raises an ImportError that the user can't otherwise see from the UI.
    """
    raw = str(err) or err.__class__.__name__
    msg = raw
    lowered = raw.lower()
    if isinstance(err, ImportError) or "no module named" in lowered:
        msg = (
            "Required ML packages aren't installed in the sidecar. Run "
            "`uv sync --extra ml` from `apps/sidecar` and retry."
        )
    elif "huggingface_hub" in lowered and "401" in lowered:
        msg = "HuggingFace returned 401 — check your HF_TOKEN if the model is gated."
    _emit(
        {
            "type": "model_error",
            "component": capability,
            "label": capability,
            "error": msg,
            "elapsed_ms": 0,
        }
    )


def _warmup_asr(cfg: Config) -> None:
    """Boot the streaming transcriber, which loads silero-vad and whisper.
    Both emit their own `model_loading` events under `asr.vad` / `asr.whisper`.
    Raises on failure — the caller wraps and surfaces a `model_error`.
    """
    from sarathi.asr.streaming import StreamingTranscriber
    from sarathi.asr.vad import VadConfig

    asr = cfg.section("asr")
    vad = cfg.section("vad")
    StreamingTranscriber(
        vad=VadConfig(
            threshold=0.5,
            min_silence_ms=vad.get("min_silence_ms", 400),
            max_segment_s=vad.get("max_segment_s", 28),
            pad_ms=int(vad.get("overlap_s", 1.5) * 1000 / 2),
        ),
        model=asr.get("model", "large-v3-turbo"),
        compute_type=asr.get("compute_type", "int8"),
        language=(asr.get("language") or None),
        no_speech_threshold=asr.get("no_speech_threshold", 0.6),
        condition_on_previous_text=asr.get("condition_on_previous_text", False),
    )


def _warmup_embed(cfg: Config) -> None:
    from sarathi.embed.bge_m3 import embed_query

    embed_query(
        "warmup",
        model=cfg.section("embed").get("model", "BAAI/bge-m3"),
    )


def _warmup_llm(cfg: Config) -> None:
    """Load the MLX LLM with a 1-token generation to force model-mmap +
    weight upload to the GPU. The actual output is discarded."""
    from sarathi.llm.mlx_runner import generate

    generate(
        system="ready",
        user="ready",
        model=cfg.section("llm").get(
            "model", "mlx-community/Qwen2.5-7B-Instruct-4bit"
        ),
        max_new_tokens=1,
        temperature=0.0,
    )


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
    db_path: Path,
    retention_days: int,
    interval_s: float,
    stop_event: threading.Event,
) -> threading.Thread:
    """Background thread: every `interval_s`, delete transcripts older than
    `retention_days`. Emits a `vacuumed` event with the deleted row count.

    The SQLite `Store` is constructed *inside the thread* so its
    connection is owned by this thread. sqlite3 by default refuses
    cross-thread use of a connection, and our retention sweep happens
    far away from the main loop's command thread, so the connection
    must be born here.
    """

    def loop() -> None:
        try:
            from sarathi.store.sqlite import Store
        except Exception as e:  # noqa: BLE001
            _err(f"vacuum thread: cannot import Store: {e}")
            return

        try:
            store = Store(db_path)
        except Exception as e:  # noqa: BLE001
            _err(f"vacuum thread: cannot open {db_path}: {e}")
            return

        try:
            # Boot vacuum first — useful when the app has been closed for
            # longer than the retention window.
            if not stop_event.is_set():
                _vacuum_once(store, retention_days)
            while not stop_event.wait(interval_s):
                _vacuum_once(store, retention_days)
        finally:
            try:
                store.close()
            except Exception:
                pass

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
        # The vacuum thread opens its own SQLite connection from this path
        # (sqlite3 refuses cross-thread connection use, and creating one
        # here on the main thread + handing it off was the bug that
        # surfaced as "SQLite objects created in a thread can only be used
        # in that same thread").
        if store is not None:
            paths = cfg.section("paths")
            db_path = cfg.resolve_path(paths.get("data_dir", "data")) / "metadata.db"
            _start_vacuum_thread(
                db_path, retention_days, vacuum_interval_s, stop_vacuum
            )

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
                    # Signal the vacuum thread to exit; it owns its own
                    # SQLite connection and closes it itself.
                    stop_vacuum.set()
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

                elif ctype == "preload":
                    components = cmd.get("components") or ["asr", "embed", "llm"]
                    summary = _preload(cfg, components)
                    _emit(
                        {
                            "type": "preload_done",
                            "components": summary,
                            "ok": all(summary.values()),
                        }
                    )

                elif ctype == "check_setup":
                    _emit(
                        {
                            "type": "setup_check",
                            "components": _check_setup(cfg),
                        }
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
