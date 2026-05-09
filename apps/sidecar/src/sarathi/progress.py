"""Model-load progress events.

The sidecar lazy-loads heavyweight models — whisper, BGE-M3, the LLM, the
reranker, the diarizer. Each one carries a multi-GB download on first
launch, then a few seconds of mmap on subsequent launches. The UI needs
to know:

  - which model is loading right now           (`model_loading`)
  - how the download is progressing            (`model_progress`)
  - when it's done                              (`model_loaded`)
  - rough size so it can show "~ 4 GB"          (in `model_loading`)

Usage pattern:

    from sarathi.progress import loading

    with loading("whisper", "Whisper large-v3-turbo", approx_mb=1000):
        from faster_whisper import WhisperModel
        model = WhisperModel(...)

While the `loading` block is active, every `tqdm` progress bar created
inside it (which is how huggingface_hub, mlx-lm, faster-whisper and
FlagEmbedding all report progress) is intercepted: bytes-downloaded /
bytes-total are summed across all live bars and emitted as
`model_progress` events, throttled to roughly 8/second.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

# Stdout writes need to interleave safely with serve.py's event emitter.
_LOCK = threading.Lock()


def _emit(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False) + "\n"
    with _LOCK:
        sys.stdout.write(line)
        sys.stdout.flush()


# ---------------------------------------------------------------------------#
# tqdm interception                                                          #
# ---------------------------------------------------------------------------#


class _TqdmTracker:
    """Aggregates byte counts across all tqdm bars and pushes a throttled
    progress event to the caller.

    Important: bars are NOT removed from the tally when they close —
    they're snapshotted as complete (current = total) and kept in the
    sum forever. Otherwise every file completion would yank that bar's
    bytes out of both the numerator and denominator, making the visible
    percent jump backwards. Keeping completed snapshots makes the
    cumulative-bytes counter monotonic.
    """

    def __init__(
        self,
        on_progress,
        throttle_ms: int = 120,
    ) -> None:
        self._on_progress = on_progress
        # bar_id -> (current_bytes, total_bytes). Stays even after close.
        self._snapshots: dict[int, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._last_emit_ms: float = 0.0
        self._throttle_ms = throttle_ms

    def register(self, key: int, bar: Any) -> None:
        with self._lock:
            t = int(getattr(bar, "total", None) or 0)
            n = int(getattr(bar, "n", None) or 0)
            self._snapshots[key] = (min(n, t) if t > 0 else n, t)
        self._maybe_emit()

    def update(self, key: int, bar: Any) -> None:
        with self._lock:
            n = int(getattr(bar, "n", None) or 0)
            t = int(getattr(bar, "total", None) or 0)
            prev = self._snapshots.get(key)
            # Lock the total in once we've seen one — protects against weird
            # tqdm subclasses that mutate `total` mid-flight.
            if prev is not None and prev[1] > 0:
                t = prev[1]
            self._snapshots[key] = (min(n, t) if t > 0 else n, t)
        self._maybe_emit()

    def unregister(self, key: int) -> None:
        with self._lock:
            prev = self._snapshots.get(key)
            if prev is None:
                return
            current, total = prev
            if total > 0:
                # Mark complete: current = total. Snapshot retained.
                self._snapshots[key] = (total, total)
            else:
                # No total ever known — drop. Keeps indeterminate bars
                # from polluting the sum with phantom downloads.
                self._snapshots.pop(key, None)
        self._maybe_emit(force=True)

    def _maybe_emit(self, *, force: bool = False) -> None:
        now_ms = time.monotonic() * 1000
        if not force and (now_ms - self._last_emit_ms) < self._throttle_ms:
            return
        self._last_emit_ms = now_ms

        with self._lock:
            snaps = list(self._snapshots.values())

        total = 0
        current = 0
        for c, t in snaps:
            if t > 0:
                total += t
                current += c

        if total > 0:
            try:
                self._on_progress(current, total)
            except Exception:
                # Never let a callback error break the underlying load.
                pass


def _patch_tqdm(tracker: _TqdmTracker) -> bool:
    """Monkey-patch the base `tqdm.std.tqdm` class so every instance routes
    through our tracker. Patches the *class* (not module-level names), so
    libraries that did `from tqdm import tqdm` long before we imported
    still hit our wrappers — they're all instances of this same class.

    Returns True if the patch was applied, False if tqdm isn't available.
    """
    try:
        import tqdm.std  # noqa: PLC0415
    except ImportError:
        return False

    cls = tqdm.std.tqdm
    if getattr(cls, "_sarathi_patched", False):
        return True  # already patched, idempotent

    orig_init = cls.__init__
    orig_update = cls.update
    orig_close = cls.close

    def new_init(self, *args, **kwargs):  # type: ignore[no-redef]
        orig_init(self, *args, **kwargs)
        tracker.register(id(self), self)

    def new_update(self, n=1):  # type: ignore[no-redef]
        ret = orig_update(self, n)
        tracker.update(id(self), self)
        return ret

    def new_close(self):  # type: ignore[no-redef]
        try:
            tracker.unregister(id(self))
        finally:
            return orig_close(self)

    cls.__init__ = new_init
    cls.update = new_update
    cls.close = new_close
    cls._sarathi_patched = True
    cls._sarathi_orig_init = orig_init
    cls._sarathi_orig_update = orig_update
    cls._sarathi_orig_close = orig_close
    return True


def _unpatch_tqdm() -> None:
    try:
        import tqdm.std  # noqa: PLC0415
    except ImportError:
        return
    cls = tqdm.std.tqdm
    if not getattr(cls, "_sarathi_patched", False):
        return
    cls.__init__ = cls._sarathi_orig_init
    cls.update = cls._sarathi_orig_update
    cls.close = cls._sarathi_orig_close
    del cls._sarathi_patched
    del cls._sarathi_orig_init
    del cls._sarathi_orig_update
    del cls._sarathi_orig_close


@contextlib.contextmanager
def _track_downloads(on_progress) -> Iterator[None]:
    """Activate tqdm interception for the duration of the block. If tqdm
    isn't installed this becomes a no-op — calls still work, no progress
    events fire."""
    tracker = _TqdmTracker(on_progress)
    patched = _patch_tqdm(tracker)
    try:
        yield
    finally:
        if patched:
            _unpatch_tqdm()


# ---------------------------------------------------------------------------#
# Cache-directory polling                                                    #
# ---------------------------------------------------------------------------#
#
# Belt-and-suspenders next to the tqdm intercept: poll the model's cache
# directory while a load is happening and report progress based on real
# bytes on disk. tqdm patching can miss bars in newer huggingface_hub
# transfer paths (xet, hf_transfer); polling the filesystem doesn't care
# how the bytes got there.


def hf_cache_root() -> Path:
    """The directory under which huggingface_hub stores model snapshots.
    Defaults to `~/.cache/huggingface/hub`; respects `HF_HOME`."""
    base = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return Path(base) / "hub"


def hf_repo_cache(repo_id: str) -> Path:
    """The on-disk path huggingface_hub uses for `repo_id` (e.g.
    `BAAI/bge-m3` → `<cache>/models--BAAI--bge-m3`)."""
    return hf_cache_root() / f"models--{repo_id.replace('/', '--')}"


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path))
            except OSError:
                pass
    except OSError:
        pass
    return total


@contextlib.contextmanager
def _watch_dirs(
    dirs: list[Path],
    on_progress,
    throttle_s: float = 0.5,
) -> Iterator[None]:
    """Background poller. While the context is active, every `throttle_s`
    seconds we measure the cumulative size of `dirs` and report the delta
    against the size at entry through `on_progress(current, total=0)`.
    Total is left as 0 — the frontend computes percent against its own
    declared `approxBytes` per row, which doesn't change as new files
    appear (so the bar stays monotonic).
    """
    if not dirs:
        yield
        return

    initial = sum(_dir_size(d) for d in dirs)
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(throttle_s):
            current = sum(_dir_size(d) for d in dirs)
            delta = max(0, current - initial)
            try:
                on_progress(delta, 0)
            except Exception:
                pass

    t = threading.Thread(target=loop, name="sarathi-cache-poller", daemon=True)
    t.start()
    try:
        yield
    finally:
        stop.set()
        # One last emit so the bar reflects the final on-disk size.
        try:
            final = sum(_dir_size(d) for d in dirs)
            on_progress(max(0, final - initial), 0)
        except Exception:
            pass


# ---------------------------------------------------------------------------#
# loading() context manager                                                  #
# ---------------------------------------------------------------------------#


@contextlib.contextmanager
def loading(
    component: str,
    label: str,
    *,
    approx_mb: int | None = None,
    cache_dirs: list[Path] | None = None,
) -> Iterator[None]:
    """Emit `model_loading` on entry, `model_loaded` on exit (or
    `model_error` if the body raises). While the body runs:

      - intercept `tqdm` and emit per-bar progress (`_track_downloads`).
      - poll any provided `cache_dirs` and emit progress based on bytes
        actually written to disk (`_watch_dirs`).

    Either source is sufficient. We run both because tqdm interception
    can miss bars in newer huggingface_hub transfer paths (xet,
    hf_transfer), and disk-polling doesn't care how the bytes got there.
    The latest report from either source wins on the frontend (which
    keeps the higher cumulative count).
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

    last_reported = [0]  # mutable cell

    def on_progress(current: int, total: int) -> None:
        # Coalesce: never report a smaller current than what we've already
        # told the frontend. The two sources can briefly disagree (tqdm
        # finishes a file, dir-poller hasn't picked up the new bytes yet,
        # or vice versa) — clamping to monotonic-up keeps the bar honest.
        c = max(int(current), last_reported[0])
        last_reported[0] = c
        percent = (c / total) * 100.0 if total else 0.0
        _emit(
            {
                "type": "model_progress",
                "component": component,
                "current_bytes": c,
                "total_bytes": int(total),
                "percent": round(min(100.0, max(0.0, percent)), 1),
            }
        )

    try:
        with (
            _track_downloads(on_progress),
            _watch_dirs(cache_dirs or [], on_progress),
        ):
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
