"""Model-load progress events.

The sidecar lazy-loads heavyweight models — whisper, BGE-M3, the LLM, the
reranker, the diarizer. Each one carries a multi-GB download on first
launch, then a few seconds of mmap on subsequent launches. The UI needs
to know:
  - which model is loading right now
  - rough size so we can show "~ 4 GB"
  - when it's done

This module emits structured events to stdout (NDJSON) that the desktop
shell forwards to the renderer. Importing from this module is cheap; only
the load functions themselves call into the heavy libraries.

Usage pattern:

    from sarathi.progress import loading

    with loading("whisper", "Whisper large-v3-turbo", approx_mb=1000):
        from faster_whisper import WhisperModel
        model = WhisperModel(...)
"""

from __future__ import annotations

import contextlib
import json
import sys
import threading
import time
from typing import Iterator

# Stdout writes need to interleave safely with serve.py's event emitter.
_LOCK = threading.Lock()


def _emit(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with _LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


@contextlib.contextmanager
def loading(
    component: str, label: str, *, approx_mb: int | None = None
) -> Iterator[None]:
    """Emit `model_loading` on entry, `model_loaded` on exit (or `model_error`
    if the body raises). The frontend uses `component` as a stable key.
    """
    started = time.monotonic()
    _emit(
        {
            "type": "model_loading",
            "component": component,
            "label": label,
            "approx_mb": approx_mb,
        }
    )
    try:
        yield
    except Exception as e:
        _emit(
            {
                "type": "model_error",
                "component": component,
                "label": label,
                "error": str(e),
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        )
        raise
    else:
        _emit(
            {
                "type": "model_loaded",
                "component": component,
                "label": label,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            }
        )
