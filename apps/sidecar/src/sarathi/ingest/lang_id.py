"""Per-block language identification.

Two-tier strategy:
  1. Cheap script-based check first: if a block contains Gujarati script
     codepoints in significant proportion, label it "gu" without paying
     the fasttext cost. Reliable because Gujarati script is unambiguous.
  2. For blocks without Gujarati codepoints, fall back to fasttext lid.176
     for general-purpose detection (en, hi, mr, etc.).

This is faster and more accurate than fasttext-only, especially for the
short blocks that paragraph-level extraction produces.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

# Gujarati Unicode range: U+0A80 .. U+0AFF
_GU_LO = 0x0A80
_GU_HI = 0x0AFF


def _gujarati_ratio(text: str) -> float:
    if not text:
        return 0.0
    total = sum(1 for ch in text if not ch.isspace())
    if total == 0:
        return 0.0
    gu = sum(1 for ch in text if _GU_LO <= ord(ch) <= _GU_HI)
    return gu / total


@lru_cache(maxsize=1)
def _load_fasttext(model_path: str):  # pragma: no cover - requires model file
    try:
        import fasttext
    except ImportError as e:
        raise RuntimeError("fasttext-wheel is required for language ID.") from e
    p = Path(model_path)
    if not p.exists():
        raise FileNotFoundError(
            f"fasttext lid.176 model not found at {p}. "
            f"Download from https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin"
        )
    return fasttext.load_model(str(p))


def detect_lang(
    text: str,
    *,
    fasttext_model: str | None = None,
    gu_threshold: float = 0.10,
    fallback: str = "en",
) -> str:
    """Return ISO 639-1 language code for a block of text.

    Args:
        text: input string.
        fasttext_model: path to lid.176.bin. If None, fasttext is skipped
            and language is "gu" (if Gujarati script present) or `fallback`.
        gu_threshold: minimum fraction of Gujarati codepoints to label "gu".
        fallback: language code to return when no signal is available.
    """
    if not text or not text.strip():
        return fallback

    if _gujarati_ratio(text) >= gu_threshold:
        return "gu"

    if fasttext_model is None:
        return fallback

    try:
        model = _load_fasttext(fasttext_model)
        # fasttext expects single-line input; flatten newlines.
        labels, _ = model.predict(text.replace("\n", " "), k=1)
        # labels look like '__label__en'
        return labels[0].removeprefix("__label__")
    except Exception:  # pragma: no cover - degrade rather than crash on ID
        return fallback
