"""Language-aware sentence splitting.

Gujarati uses indic_nlp_library, which knows about purna viram (।)
in addition to ASCII full stop, ?, !.

English uses pysbd (Pragmatic Sentence Boundary Disambiguation).

For language-agnostic input (lang=None), defaults to English splitter,
which handles ASCII punctuation reasonably for mixed text. If you have
mixed-language documents, split into language-tagged blocks first
(via ingest.lang_id) and call this per block.
"""

from __future__ import annotations

from functools import lru_cache

# Languages we explicitly support; any other code falls back to English.
SUPPORTED_LANGS = frozenset({"en", "gu"})


@lru_cache(maxsize=4)
def _en_segmenter():
    try:
        import pysbd
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pysbd is required. Install with: uv add pysbd") from e
    return pysbd.Segmenter(language="en", clean=False)


@lru_cache(maxsize=1)
def _gu_splitter():
    try:
        from indicnlp.tokenize import sentence_tokenize
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "indic-nlp-library is required for Gujarati sentence splitting."
        ) from e
    return sentence_tokenize.sentence_split


def split_sentences(text: str, lang: str | None = None) -> list[str]:
    """Split a paragraph/block of text into sentences.

    Args:
        text: input text. Should already be normalized (see textproc.normalize).
        lang: ISO 639-1 code. "gu" → indic_nlp_library, else → pysbd English.

    Returns:
        List of sentence strings. Trims surrounding whitespace; drops empties.
    """
    if not text or not text.strip():
        return []

    if lang == "gu":
        sents = _gu_splitter()(text, lang="gu")
    else:
        sents = _en_segmenter().segment(text)

    return [s.strip() for s in sents if s and s.strip()]
