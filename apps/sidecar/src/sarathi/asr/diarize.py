"""Speaker diarization for streaming utterances.

Uses pyannote.audio 3.x. The model expects ≥3 seconds of audio for stable
clustering, so very short utterances will fall back to a single speaker
label. We also constrain to 2 speakers (`min_speakers=1, max_speakers=2`)
because the v0 use case is 1:1 calls — opening up the bound makes the
model spuriously split a single speaker into two on noisy clips.

Model is gated on Hugging Face (license click-through). User must:
  1. Visit https://huggingface.co/pyannote/speaker-diarization-3.1
  2. Accept the license.
  3. Set `HF_TOKEN` env var to a token with read access.

Without that, this module raises a clear error rather than silently
falling back, so the app can surface the requirement.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

SR = 16000


@dataclass
class SpeakerSegment:
    start_s: float
    end_s: float
    speaker: str  # e.g. "SPEAKER_00"


@lru_cache(maxsize=1)
def _load_pipeline(model: str, hf_token: str | None):
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "pyannote.audio and torch are required for diarization. "
            "Install with: uv sync --extra ml"
        ) from e

    if not hf_token:
        raise RuntimeError(
            "HF_TOKEN is required for pyannote diarization. "
            "Accept the model license at "
            "https://huggingface.co/pyannote/speaker-diarization-3.1 "
            "and set HF_TOKEN."
        )

    pipe = Pipeline.from_pretrained(model, use_auth_token=hf_token)
    # Apple Silicon: prefer Metal Performance Shaders (MPS).
    if torch.backends.mps.is_available():
        try:
            pipe.to(torch.device("mps"))
        except Exception:
            # Some pyannote ops don't support MPS yet; CPU fallback is fine.
            pipe.to(torch.device("cpu"))
    return pipe


class Diarizer:
    """One-shot diarization over a single utterance.

    For streaming use, call `diarize_utterance(pcm_int16, ...)` per VAD-
    segmented utterance. The result is a list of SpeakerSegment relative
    to the utterance's local time (start_s = 0).
    """

    def __init__(
        self,
        *,
        model: str = "pyannote/speaker-diarization-3.1",
        hf_token: str | None = None,
        min_duration_s: float = 1.0,
    ):
        self.model = model
        self.hf_token = hf_token or os.environ.get("HF_TOKEN")
        self.min_duration_s = min_duration_s
        self._pipe = None  # lazy

    def _ensure(self):
        if self._pipe is None:
            self._pipe = _load_pipeline(self.model, self.hf_token)

    def diarize_utterance(
        self, pcm_int16: np.ndarray, sample_rate: int = SR
    ) -> list[SpeakerSegment]:
        """Run diarization on one utterance. Returns segments in local time."""
        if pcm_int16.size == 0:
            return []
        duration_s = pcm_int16.size / sample_rate
        if duration_s < self.min_duration_s:
            # Too short for stable clustering — caller should fall back to
            # the previous utterance's speaker label or "unknown".
            return []

        self._ensure()
        import torch

        # pyannote expects float32 in shape (channels, samples).
        wav = torch.from_numpy(pcm_int16.astype(np.float32) / 32768.0).unsqueeze(0)
        result = self._pipe(
            {"waveform": wav, "sample_rate": sample_rate},
            min_speakers=1,
            max_speakers=2,
        )
        out: list[SpeakerSegment] = []
        for turn, _, speaker in result.itertracks(yield_label=True):
            out.append(
                SpeakerSegment(
                    start_s=float(turn.start),
                    end_s=float(turn.end),
                    speaker=str(speaker),
                )
            )
        return out


def dominant_speaker(segments: list[SpeakerSegment]) -> str | None:
    """Pick the speaker who occupies the most time across segments."""
    if not segments:
        return None
    totals: dict[str, float] = {}
    for s in segments:
        totals[s.speaker] = totals.get(s.speaker, 0.0) + max(0.0, s.end_s - s.start_s)
    return max(totals.items(), key=lambda kv: kv[1])[0]
