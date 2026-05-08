"""Silero-VAD wrapper for streaming utterance segmentation.

Silero VAD operates on fixed 32ms frames at 16kHz (512 samples). Our
streaming consumer feeds PCM in arbitrary-sized chunks; this module
buffers internally and emits utterance boundaries as samples flow.

Behavior:
- Tracks a current "in-speech" state via VAD probability.
- Trailing silence > min_silence_ms → flush the current utterance.
- Active speech > max_segment_s → force-flush (long monologues).
- Pre-roll of `pad_ms` audio is prepended to each utterance to avoid
  clipping word onsets, and `pad_ms` of trailing silence is included
  to give whisper natural decay.

The frame size is fixed by silero (16000 Hz × 32 ms = 512 samples),
so callers feed mono int16 PCM and we slice it ourselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator

import numpy as np

SR = 16000
FRAME_SAMPLES = 512  # silero-vad's fixed frame size at 16kHz
FRAME_MS = FRAME_SAMPLES * 1000 // SR  # 32


@dataclass
class Utterance:
    pcm: np.ndarray  # int16 mono at 16kHz
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class VadConfig:
    threshold: float = 0.5             # speech probability threshold
    min_silence_ms: int = 400          # trailing silence to end an utterance
    max_segment_s: float = 28.0        # force-flush after this much speech
    pad_ms: int = 200                  # pre/post padding around utterances
    min_utterance_ms: int = 250        # discard sub-threshold blips


@lru_cache(maxsize=1)
def _load_silero():
    try:
        import torch
        from silero_vad import load_silero_vad
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "silero-vad and torch are required. Install with: uv sync --extra ml"
        ) from e
    model = load_silero_vad()
    model.eval()
    # Set torch threads conservative — VAD is tiny, more threads hurt.
    torch.set_num_threads(1)
    return model


class StreamingVad:
    """Frame-driven VAD that yields utterances as they complete.

    Use:
        vad = StreamingVad()
        for u in vad.feed(pcm_int16):
            transcribe(u)
        for u in vad.flush():
            transcribe(u)
    """

    def __init__(self, config: VadConfig | None = None):
        self.cfg = config or VadConfig()
        self._model = _load_silero()
        self._buf = np.zeros(0, dtype=np.int16)        # un-VAD'd tail
        self._utt: list[np.ndarray] = []                # frames in current utterance
        self._utt_start_sample: int | None = None
        self._silence_frames = 0
        self._total_samples_consumed = 0
        self._pad_frames = max(1, self.cfg.pad_ms // FRAME_MS)
        self._min_silence_frames = max(1, self.cfg.min_silence_ms // FRAME_MS)
        self._max_segment_frames = int(self.cfg.max_segment_s * 1000 / FRAME_MS)
        self._min_utt_frames = max(1, self.cfg.min_utterance_ms // FRAME_MS)
        # Rolling pre-roll buffer for pre-padding utterances with audio
        # that arrived just before the speech onset.
        self._preroll: list[np.ndarray] = []

    # ------------------------------------------------------------------ #

    def feed(self, pcm_int16: np.ndarray) -> Iterator[Utterance]:
        if pcm_int16.dtype != np.int16:
            raise ValueError("pcm_int16 must be int16 PCM")
        self._buf = np.concatenate([self._buf, pcm_int16])

        while len(self._buf) >= FRAME_SAMPLES:
            frame = self._buf[:FRAME_SAMPLES]
            self._buf = self._buf[FRAME_SAMPLES:]
            yield from self._process_frame(frame)

    def flush(self) -> Iterator[Utterance]:
        if self._utt:
            yield self._build_utterance()
        self._buf = np.zeros(0, dtype=np.int16)
        self._utt = []
        self._utt_start_sample = None
        self._silence_frames = 0
        self._preroll = []

    # ------------------------------------------------------------------ #

    def _process_frame(self, frame: np.ndarray) -> Iterator[Utterance]:
        import torch

        # silero expects float32 in [-1, 1].
        f32 = frame.astype(np.float32) / 32768.0
        prob = float(self._model(torch.from_numpy(f32), SR).item())
        is_speech = prob >= self.cfg.threshold

        # Maintain pre-roll buffer regardless of state.
        self._preroll.append(frame)
        if len(self._preroll) > self._pad_frames:
            self._preroll.pop(0)

        if is_speech:
            if not self._utt:
                # New utterance: start with pre-roll padding.
                self._utt = list(self._preroll[:-1])  # exclude current frame; we'll add below
                self._utt_start_sample = self._total_samples_consumed - len(self._utt) * FRAME_SAMPLES
            self._utt.append(frame)
            self._silence_frames = 0
        elif self._utt:
            # Currently in speech, frame is silence — buffer it as potential trailing.
            self._utt.append(frame)
            self._silence_frames += 1

        # End of utterance: trailing silence reached threshold.
        if self._utt and self._silence_frames >= self._min_silence_frames:
            yield self._build_utterance()
            self._utt = []
            self._utt_start_sample = None
            self._silence_frames = 0

        # Force-flush long utterances.
        elif len(self._utt) >= self._max_segment_frames:
            yield self._build_utterance()
            self._utt = []
            self._utt_start_sample = None
            self._silence_frames = 0

        self._total_samples_consumed += FRAME_SAMPLES

    def _build_utterance(self) -> Utterance:
        # Drop short blips.
        if len(self._utt) < self._min_utt_frames:
            # Return a zero-length stub; caller filters by duration_s.
            empty = np.zeros(0, dtype=np.int16)
            return Utterance(pcm=empty, start_s=0.0, end_s=0.0)

        pcm = np.concatenate(self._utt)
        start_sample = self._utt_start_sample or 0
        end_sample = start_sample + len(pcm)
        return Utterance(
            pcm=pcm,
            start_s=start_sample / SR,
            end_s=end_sample / SR,
        )
