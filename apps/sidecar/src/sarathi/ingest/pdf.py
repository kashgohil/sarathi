"""PDF ingestion via PyMuPDF (fitz).

Strategy:
- Try the text layer first. PyMuPDF's "blocks" extraction preserves
  paragraph-shaped grouping.
- If a page has no extractable text (or text that is mostly replacement
  characters / private-use area junk, indicating an image-only page),
  fall back to OCR (sarathi.ingest.ocr) for that specific page.

Images embedded in otherwise-text PDFs are NOT auto-OCR'd here — that
should be a downstream decision once we have a per-doc cost budget.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sarathi.ingest.types import Block

# Heuristic: if more than this fraction of characters are replacement
# chars, assume the text layer is corrupted and OCR the page instead.
_BAD_CHAR_THRESHOLD = 0.15
_BAD_CHARS = {"�"}  # add private-use range checks if needed later

# Below this length, we treat a page's extracted text as "essentially empty"
# and prefer OCR. Tuned conservatively to avoid OCR'ing real-but-short pages.
_EMPTY_PAGE_CHAR_LIMIT = 20


def _looks_like_garbage(text: str) -> bool:
    if len(text) < _EMPTY_PAGE_CHAR_LIMIT:
        return True
    bad = sum(1 for ch in text if ch in _BAD_CHARS)
    return (bad / max(1, len(text))) > _BAD_CHAR_THRESHOLD


def _extract_text_layer(page) -> list[Block]:
    """PyMuPDF blocks → our Block dataclass.

    page.get_text("blocks") returns tuples
    (x0, y0, x1, y1, text, block_no, block_type).
    block_type 0 = text, 1 = image. We skip images here.
    """
    blocks: list[Block] = []
    raw = page.get_text("blocks")
    for x0, y0, x1, y1, text, block_no, block_type in raw:
        if block_type != 0:
            continue
        cleaned = text.strip()
        if not cleaned:
            continue
        blocks.append(
            Block(
                text=cleaned,
                page=page.number + 1,  # 1-indexed for UX
                source="",  # filled in by caller
                block_index=block_no,
                bbox=(float(x0), float(y0), float(x1), float(y1)),
                is_ocr=False,
            )
        )
    return blocks


def extract_pdf(
    path: str | Path,
    *,
    ocr_fn=None,
) -> Iterator[Block]:
    """Yield Blocks for a PDF, page by page.

    Args:
        path: filesystem path to the PDF.
        ocr_fn: optional callable taking (image_bytes, page_num) -> list[Block].
            If provided, used for pages whose text layer looks empty/garbage.
            If omitted, such pages produce no blocks (logged via metadata).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pymupdf is required for PDF ingestion.") from e

    src = str(Path(path).resolve())
    with fitz.open(src) as doc:
        for page in doc:
            blocks = _extract_text_layer(page)
            page_text = "\n".join(b.text for b in blocks)

            if blocks and not _looks_like_garbage(page_text):
                for b in blocks:
                    yield Block(
                        text=b.text,
                        page=b.page,
                        source=src,
                        block_index=b.block_index,
                        bbox=b.bbox,
                        is_ocr=False,
                    )
                continue

            # Text layer empty or garbage → OCR if we have an OCR function.
            if ocr_fn is None:
                # Surface a single empty Block tagged so callers can log it.
                yield Block(
                    text="",
                    page=page.number + 1,
                    source=src,
                    block_index=0,
                    is_ocr=False,
                    metadata={"skip_reason": "no_text_layer_no_ocr"},
                )
                continue

            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            for b in ocr_fn(img_bytes, page.number + 1):
                yield Block(
                    text=b.text,
                    page=b.page,
                    source=src,
                    block_index=b.block_index,
                    bbox=b.bbox,
                    is_ocr=True,
                    ocr_confidence=b.ocr_confidence,
                )
