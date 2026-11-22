"""Text-layer extraction and OCR fallback policy."""

from __future__ import annotations

import logging
import string
from pathlib import Path

from trop.ingest.ocr import ocr_image
from trop.ingest.pdf_backend import PdfBackend, open_backend
from trop.models import Document, Line, Page, TextSource, Word
from trop.settings import OcrSettings

logger = logging.getLogger(__name__)

_PRINTABLE = set(string.printable)


def printable_stats(text: str) -> tuple[int, float]:
    """Return (printable_char_count, printable_ratio over non-whitespace length)."""
    if not text:
        return 0, 0.0
    # Count characters that are printable (incl. space); ratio vs all chars.
    printable = sum(1 for ch in text if ch in _PRINTABLE or ch.isprintable())
    total = len(text)
    ratio = printable / total if total else 0.0
    # "Printable chars" for the min_chars threshold: strip whitespace noise.
    meaningful = sum(
        1
        for ch in text
        if (ch in _PRINTABLE or ch.isprintable()) and not ch.isspace()
    )
    return meaningful, ratio


def text_is_usable(
    text: str,
    *,
    min_chars: int = 40,
    min_printable_ratio: float = 0.9,
) -> bool:
    """True when the PDF text layer is rich enough to skip OCR."""
    meaningful, ratio = printable_stats(text)
    return meaningful >= min_chars and ratio >= min_printable_ratio


def lines_from_plain_text(text: str) -> list[Line]:
    """Split plain text into Line/Word structures (no geometry)."""
    lines: list[Line] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        words = [Word(text=tok) for tok in stripped.split() if tok]
        lines.append(Line(text=stripped, words=words))
    return lines


def ingest_document(
    path: Path,
    *,
    relative_path: Path | None = None,
    dpi: int = 200,
    ocr: OcrSettings | None = None,
    max_pages: int | None = 40,
    backend: PdfBackend | None = None,
) -> Document:
    """Open PDF, extract text per page, OCR pages with unusable text layers."""
    ocr_cfg = ocr or OcrSettings()
    rel = relative_path if relative_path is not None else Path(path.name)
    doc = Document(path=Path(path), relative_path=rel)
    own_backend = backend is None
    pdf = backend or open_backend(path)
    ocr_budget = ocr_cfg.max_pages
    try:
        n = pdf.page_count()
        doc.page_count = n
        limit = n if max_pages is None or max_pages <= 0 else min(n, max_pages)
        if limit < n:
            logger.info(
                "Capping %s to %s/%s pages (max_pages=%s)",
                path.name,
                limit,
                n,
                max_pages,
            )
        ocr_used = 0
        for i in range(limit):
            allow_ocr = True
            if ocr_budget is not None and ocr_budget >= 0 and ocr_used >= ocr_budget:
                allow_ocr = False
            page = _ingest_page(
                pdf,
                i,
                dpi=dpi,
                ocr_cfg=ocr_cfg,
                allow_ocr=allow_ocr,
            )
            if page.used_ocr:
                ocr_used += 1
            doc.pages.append(page)
    finally:
        if own_backend:
            pdf.close()
    return doc


def _ingest_page(
    pdf: PdfBackend,
    index: int,
    *,
    dpi: int,
    ocr_cfg: OcrSettings,
    allow_ocr: bool = True,
) -> Page:
    width, height = pdf.page_size(index)
    raw_text = pdf.extract_text(index) or ""
    meaningful, ratio = printable_stats(raw_text)
    page = Page(
        index=index,
        width=width,
        height=height,
        text=raw_text,
        lines=lines_from_plain_text(raw_text),
        printable_chars=meaningful,
        printable_ratio=ratio,
        source=TextSource.PDF_TEXT if raw_text.strip() else TextSource.EMPTY,
    )

    needs_ocr = (
        allow_ocr
        and ocr_cfg.enabled
        and not text_is_usable(
            raw_text,
            min_chars=ocr_cfg.min_chars,
            min_printable_ratio=ocr_cfg.min_printable_ratio,
        )
    )
    if not needs_ocr:
        return page

    logger.debug(
        "Page %s text unusable (chars=%s ratio=%.3f) → OCR",
        index,
        meaningful,
        ratio,
    )
    rendered = pdf.render_page(index, dpi=dpi)
    ocr_text, ocr_lines = ocr_image(rendered.image)
    page.text = ocr_text
    page.lines = ocr_lines
    page.used_ocr = True
    meaningful, ratio = printable_stats(ocr_text)
    page.printable_chars = meaningful
    page.printable_ratio = ratio
    page.source = TextSource.OCR if ocr_text.strip() else TextSource.EMPTY
    return page
