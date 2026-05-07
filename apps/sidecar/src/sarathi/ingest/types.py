"""Shared types for the ingest pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Block:
    """A contiguous block of text from a source doc.

    Blocks are the unit of language ID and (eventually) chunking. A page
    of a PDF typically yields several blocks (one per visual paragraph
    or column section).
    """

    text: str
    page: int
    source: str  # absolute path or URI of the source file
    lang: str | None = None  # filled in by lang_id
    block_index: int = 0  # ordering within the doc
    bbox: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 if known
    is_ocr: bool = False
    ocr_confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
