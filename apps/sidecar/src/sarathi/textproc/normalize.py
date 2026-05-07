"""Unicode normalization for Indic + Latin text.

Pipeline:
  1. NFC normalize (canonical composition).
  2. For Gujarati blocks: run indic_nlp_library's normalizer to canonicalise
     nukta variants and combining marks.
  3. Strip stray ZWJ (U+200D) / ZWNJ (U+200C) only when between non-conjuncts.
  4. Collapse runs of whitespace, preserve paragraph breaks (\\n\\n).

The normalizer is intentionally idempotent — calling it twice gives the same
output. That makes it safe to apply at multiple pipeline stages without
worrying about double-normalization corrupting text.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

import regex as re

# Lazy-imported because indic-nlp-library is heavy and not always installed.
_GU_NORMALIZER = None

# Match ZWJ/ZWNJ that are NOT adjacent to a virama (U+0ACD for Gujarati).
# Virama is the conjunct-forming character; ZWJ/ZWNJ near it are grammatical.
_STRAY_ZW = re.compile(r"(?<![્])[‌‍](?![્])")

# Whitespace runs (but preserve double newlines as paragraph breaks).
_WS_PARA = re.compile(r"\n{2,}")
_WS_INLINE = re.compile(r"[ \t\f\v\r]+")
_WS_NEWLINE = re.compile(r"\n[ \t]+")


@lru_cache(maxsize=1)
def _get_gu_normalizer():
    try:
        from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "indic-nlp-library is required for Gujarati normalization. "
            "Install with: uv add indic-nlp-library"
        ) from e
    return IndicNormalizerFactory().get_normalizer("gu")


def _gu_normalize(text: str) -> str:
    return _get_gu_normalizer().normalize(text)


def normalize(text: str, lang: str | None = None) -> str:
    """Normalize text for downstream embedding/retrieval.

    Args:
        text: input string.
        lang: ISO 639-1 language code. If "gu", apply Gujarati-specific
            normalization. Other values fall through to NFC + whitespace-only.
            None is treated as language-agnostic.

    Returns:
        Normalized string. Idempotent.
    """
    if not text:
        return ""

    # 1. NFC — canonical composition.
    out = unicodedata.normalize("NFC", text)

    # 2. Indic-specific normalization.
    if lang == "gu":
        out = _gu_normalize(out)
        # indic-nlp-library may emit NFD-ish forms; re-NFC to be safe.
        out = unicodedata.normalize("NFC", out)

    # 3. Strip stray ZWJ/ZWNJ.
    out = _STRAY_ZW.sub("", out)

    # 4. Whitespace cleanup. Preserve paragraph breaks.
    out = _WS_NEWLINE.sub("\n", out)
    out = _WS_INLINE.sub(" ", out)
    out = _WS_PARA.sub("\n\n", out)

    return out.strip()
