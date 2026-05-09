"""Streaming ASR: VAD-segmented utterances → faster-whisper.

This is utterance-level streaming, not word-level partials. The choice
is deliberate:
- Word-level partials require a streaming-aware decoder (whisper-streaming
  or whisperX) and add a lot of complexity for marginal UX benefit when
  retrieval/answer happens at utterance boundaries anyway.
- Utterance latency on M4 is dominated by whisper inference (~0.3-0.5x
  realtime for large-v3 int8_float16), so a 5-second utterance lands
  ~1.5–2.5s after speech ends. Acceptable for the v0 use case.

If sub-second feedback becomes a requirement, swap in whisperX or run
distil-whisper on partials with large-v3 as the final pass.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from sarathi.asr.vad import SR, StreamingVad, Utterance, VadConfig


@dataclass
class StreamSegment:
    text: str
    start_s: float
    end_s: float
    language: str | None
    avg_logprob: float | None = None
    speaker_id: str | None = None


@lru_cache(maxsize=2)
def _load_whisper(model_name: str, compute_type: str, device: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "faster-whisper is required. Install with: uv sync --extra ml"
        ) from e
    from sarathi.progress import hf_repo_cache, loading

    approx = 1000 if "turbo" in model_name else 3000
    with loading(
        "asr.whisper",
        f"Whisper {model_name} ({compute_type})",
        approx_mb=approx,
        cache_dirs=[hf_repo_cache(f"Systran/faster-whisper-{model_name}")],
    ):
        return WhisperModel(model_name, device=device, compute_type=compute_type)


class StreamingTranscriber:
    """Holds VAD + whisper state, exposes feed/flush returning StreamSegments."""

    def __init__(
        self,
        *,
        vad: VadConfig | None = None,
        model: str = "large-v3",
        compute_type: str = "int8_float16",
        device: str = "auto",
        language: str | None = None,
        no_speech_threshold: float = 0.6,
        condition_on_previous_text: bool = False,
        diarizer=None,  # optional Diarizer instance; tags segments with speaker_id
    ):
        self._vad = StreamingVad(vad)
        self._wm = _load_whisper(model, compute_type, device)
        self._language = language
        self._no_speech_threshold = no_speech_threshold
        self._condition = condition_on_previous_text
        self._diarizer = diarizer
        self._last_speaker: str | None = None

    def feed(self, pcm_int16: np.ndarray) -> Iterator[StreamSegment]:
        for utt in self._vad.feed(pcm_int16):
            seg = self._transcribe(utt)
            if seg is not None:
                yield seg

    def flush(self) -> Iterator[StreamSegment]:
        for utt in self._vad.flush():
            seg = self._transcribe(utt)
            if seg is not None:
                yield seg

    def _transcribe(self, utt: Utterance) -> StreamSegment | None:
        if utt.duration_s < 0.25 or len(utt.pcm) == 0:
            return None

        # faster-whisper accepts a numpy float32 array at 16kHz directly.
        audio = utt.pcm.astype(np.float32) / 32768.0
        seg_iter, info = self._wm.transcribe(
            audio,
            language=self._language,
            no_speech_threshold=self._no_speech_threshold,
            condition_on_previous_text=self._condition,
            vad_filter=False,  # we already VAD-segmented; double-VAD hurts
        )

        parts: list[str] = []
        avg_logprobs: list[float] = []
        for s in seg_iter:
            t = s.text.strip()
            if not t:
                continue
            parts.append(t)
            if getattr(s, "avg_logprob", None) is not None:
                avg_logprobs.append(s.avg_logprob)

        text = " ".join(parts).strip()
        if not text:
            return None

        speaker_id = self._diarize_one(utt)

        return StreamSegment(
            text=text,
            start_s=utt.start_s,
            end_s=utt.end_s,
            language=info.language,
            avg_logprob=(sum(avg_logprobs) / len(avg_logprobs)) if avg_logprobs else None,
            speaker_id=speaker_id,
        )

    def _diarize_one(self, utt: Utterance) -> str | None:
        """Diarize a single utterance. If too short for stable clustering or
        diarization is unavailable, fall back to the previous label."""
        if self._diarizer is None:
            return None
        try:
            segs = self._diarizer.diarize_utterance(utt.pcm)
        except RuntimeError:
            # Module loaded but model unavailable (no token, license, etc).
            self._diarizer = None
            return None
        except Exception:
            return self._last_speaker

        if not segs:
            return self._last_speaker

        from sarathi.asr.diarize import dominant_speaker

        sp = dominant_speaker(segs)
        if sp is not None:
            self._last_speaker = sp
        return sp
