"""OCR fallback for image-only PDFs and standalone images.

Uses PaddleOCR with multilingual models (devanagari covers Gujarati
acceptably; for higher-quality Gujarati a fine-tuned model can be
swapped in via config). Tesseract `guj+eng` is left as a future fallback.

This module is a skeleton: the heavy paddle import is deferred to the
first call so the rest of the sidecar can run without paddlepaddle
installed (it's an optional `[ml]` extra in pyproject.toml).
"""

from __future__ import annotations

from functools import lru_cache

from sarathi.ingest.types import Block


@lru_cache(maxsize=1)
def _get_paddle_ocr():  # pragma: no cover - heavy ML
    try:
        from paddleocr import PaddleOCR
    except ImportError as e:
        raise RuntimeError(
            "paddleocr is required for OCR. Install with: uv add 'sarathi-sidecar[ml]'"
        ) from e
    # `lang='devanagari'` provides reasonable Gujarati coverage; revisit
    # with a Gujarati-specific recognizer once we have eval numbers.
    return PaddleOCR(use_angle_cls=True, lang="devanagari", show_log=False)


def ocr_image(img_bytes: bytes, page_num: int = 1) -> list[Block]:  # pragma: no cover
    """Run OCR on PNG/JPEG image bytes.

    Returns a list of Blocks, one per detected text line. `bbox` is the
    quad bounding box (x0, y0, x1, y1) of the line.
    """
    import io

    import numpy as np
    from PIL import Image

    ocr = _get_paddle_ocr()
    img = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))
    result = ocr.ocr(img, cls=True)

    blocks: list[Block] = []
    if not result or not result[0]:
        return blocks

    for idx, line in enumerate(result[0]):
        quad, (text, conf) = line
        if not text or not text.strip():
            continue
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        blocks.append(
            Block(
                text=text.strip(),
                page=page_num,
                source="",  # filled in by caller
                block_index=idx,
                bbox=bbox,
                is_ocr=True,
                ocr_confidence=float(conf),
            )
        )
    return blocks
