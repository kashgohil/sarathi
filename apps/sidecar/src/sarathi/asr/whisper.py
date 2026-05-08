"""ASR via faster-whisper.

Why faster-whisper:
- CTranslate2 backend is meaningfully faster than the reference whisper
  on Apple Silicon, with comparable WER on Gujarati for large-v3.
- Supports int8/float16 quantizations that fit comfortably alongside
  the LLM in unified memory on M-series.

Streaming variant lives in `sarathi.asr.streaming` (M2). This module
covers the file-based path used by `sarathi run` and the eval harness.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass
class Segment:
    start: float
    end: float
    text: str
    language: str | None = None
    avg_logprob: float | None = None


@dataclass
class Transcript:
    text: str
    segments: list[Segment]
    language: str | None
    duration: float


@lru_cache(maxsize=2)
def _load_model(model_name: str, compute_type: str, device: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "faster-whisper is required for ASR. "
            "Install with: uv sync --extra ml"
        ) from e
    from sarathi.progress import loading

    approx = 1000 if "turbo" in model_name else 3000
    with loading(
        "asr.whisper",
        f"Whisper {model_name} ({compute_type})",
        approx_mb=approx,
    ):
        return WhisperModel(model_name, device=device, compute_type=compute_type)


def transcribe_file(
    audio_path: str | Path,
    *,
    model: str = "large-v3",
    compute_type: str = "int8_float16",
    language: str | None = None,
    no_speech_threshold: float = 0.6,
    condition_on_previous_text: bool = False,
    device: str = "auto",
) -> Transcript:
    """Transcribe an audio file end-to-end.

    Args:
        audio_path: any format faster-whisper / ffmpeg can read.
        model: faster-whisper model name (e.g., "large-v3", "large-v3-turbo").
        compute_type: quantization (int8, int8_float16, float16, float32).
        language: ISO 639-1 code, or None for auto-detect.
        no_speech_threshold: raised from default to suppress hallucinations
            on silence (a known whisper failure mode for Gujarati).
        condition_on_previous_text: False = each segment decoded independently
            to prevent compounding hallucinations.
        device: "auto", "cpu", "cuda".
    """
    audio_path = str(Path(audio_path).resolve())
    m = _load_model(model, compute_type, device)

    seg_iter, info = m.transcribe(
        audio_path,
        language=language,
        no_speech_threshold=no_speech_threshold,
        condition_on_previous_text=condition_on_previous_text,
        vad_filter=True,  # built-in silero gate; good default for our use
    )

    segments: list[Segment] = []
    parts: list[str] = []
    for seg in seg_iter:
        text = seg.text.strip()
        if not text:
            continue
        segments.append(
            Segment(
                start=float(seg.start),
                end=float(seg.end),
                text=text,
                language=getattr(seg, "language", None) or info.language,
                avg_logprob=getattr(seg, "avg_logprob", None),
            )
        )
        parts.append(text)

    return Transcript(
        text=" ".join(parts).strip(),
        segments=segments,
        language=info.language,
        duration=float(info.duration),
    )


def asr_config_from(cfg: Any) -> dict:
    """Pluck ASR options out of a sarathi.config.Config."""
    s = cfg.section("asr")
    return {
        "model": s.get("model", "large-v3"),
        "compute_type": s.get("compute_type", "int8_float16"),
        "language": (s.get("language") or None),  # empty string → None
        "no_speech_threshold": s.get("no_speech_threshold", 0.6),
        "condition_on_previous_text": s.get("condition_on_previous_text", False),
    }
