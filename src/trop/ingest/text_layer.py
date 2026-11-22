"""Text-layer extraction and OCR fallback policy."""

from __future__ import annotations

import logging
import re
import string
from pathlib import Path

from trop.ingest.ocr import ocr_image
from trop.ingest.pdf_backend import PdfBackend, open_backend
from trop.models import Document, Line, Page, TextSource, Word
from trop.settings import OcrSettings

logger = logging.getLogger(__name__)

_PRINTABLE = set(string.printable)

# Full-page OCR sometimes obliterates stamped "nr referencyjny" / BZP lines;
# a higher-DPI horizontal band pass often recovers them.
_REF_LABEL = re.compile(r"(?i)nr\s*referencyj")
_REF_VALUE = re.compile(r"(?i)nr\s*referencyj\w*\s*:?\s*([^\n]{0,100})")
_HAS_PROC_OR_BZP = re.compile(
    r"(?i)(?:\b[A-Z]{1,6}[./]\d{1,4}[./]\d{2,4}\b|\d{4}\s*/\s*BZP|\bOPZ\b)"
)


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
            page, ocr_attempted = _ingest_page(
                pdf,
                i,
                dpi=dpi,
                ocr_cfg=ocr_cfg,
                allow_ocr=allow_ocr,
            )
            # The budget caps OCR cost, so count attempts even when the
            # text layer was kept.
            if ocr_attempted:
                ocr_used += 1
            doc.pages.append(page)
    finally:
        if own_backend:
            pdf.close()
    return doc


def prefer_ocr(
    *,
    text_chars: int,
    text_ratio: float,
    ocr_chars: int,
    ocr_cfg: OcrSettings,
) -> bool:
    """Decide whether an OCR reading should replace the page's text layer.

    A garbled or empty text layer gives way to any OCR text. A genuine but
    short one (signature / date page) is exact, so OCR only wins when it adds
    at least a page's worth (``min_chars``) — e.g. a scan with a text stamp.
    """
    if ocr_chars == 0:
        return False
    text_trusted = text_chars > 0 and text_ratio >= ocr_cfg.min_printable_ratio
    if not text_trusted:
        return True
    return ocr_chars >= text_chars + ocr_cfg.min_chars


def _ingest_page(
    pdf: PdfBackend,
    index: int,
    *,
    dpi: int,
    ocr_cfg: OcrSettings,
    allow_ocr: bool = True,
) -> tuple[Page, bool]:
    """Return ``(page, ocr_attempted)``."""
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
        return page, False

    logger.debug(
        "Page %s text unusable (chars=%s ratio=%.3f) → OCR",
        index,
        meaningful,
        ratio,
    )
    rendered = pdf.render_page(index, dpi=dpi)
    ocr_text, ocr_lines = ocr_image(rendered.image)
    ocr_meaningful, ocr_ratio = printable_stats(ocr_text)
    if not prefer_ocr(
        text_chars=meaningful,
        text_ratio=ratio,
        ocr_chars=ocr_meaningful,
        ocr_cfg=ocr_cfg,
    ):
        logger.debug(
            "Page %s: keeping text layer (%s chars) over OCR (%s chars)",
            index,
            meaningful,
            ocr_meaningful,
        )
        return page, True
    page.text = ocr_text
    page.lines = ocr_lines
    page.used_ocr = True
    page.printable_chars = ocr_meaningful
    page.printable_ratio = ocr_ratio
    page.source = TextSource.OCR
    _maybe_refine_referencyjny_band(pdf, index, dpi=dpi, page=page)
    return page, True


def _referencyjny_looks_broken(text: str) -> bool:
    """True when a referencyjny cue exists but no procedure/BZP/OPZ token nearby."""
    if not text or not _REF_LABEL.search(text):
        return False
    if _HAS_PROC_OR_BZP.search(text):
        return False
    m = _REF_VALUE.search(text)
    if not m:
        return True
    # Digits alone in the tail are usually OCR noise ("Z     e     ien").
    return not re.search(r"[A-Za-z]{1,6}\s*/\s*\d", m.group(1))


def _maybe_refine_referencyjny_band(
    pdf: PdfBackend,
    index: int,
    *,
    dpi: int,
    page: Page,
) -> None:
    """Re-OCR mid-page bands at higher DPI when procedure numbers look destroyed."""
    if not _referencyjny_looks_broken(page.text or ""):
        return
    band_dpi = min(max(dpi + 150, 300), 350)
    try:
        image = pdf.render_page(index, dpi=band_dpi).image
    except Exception:  # noqa: BLE001
        logger.debug("Page %s: band re-OCR render failed", index, exc_info=True)
        return
    if image is None or getattr(image, "size", 0) == 0:
        return
    height = int(image.shape[0])
    # Narrow bands: wider crops confuse the detector on stamped scans.
    recovered: list[str] = []
    for y0, y1 in ((0.55, 0.78), (0.58, 0.82), (0.50, 0.70)):
        y_a, y_b = int(height * y0), int(height * y1)
        if y_b <= y_a:
            continue
        band_text, _ = ocr_image(image[y_a:y_b, :])
        if band_text and _HAS_PROC_OR_BZP.search(band_text):
            recovered.append(band_text.strip())
    if not recovered:
        return
    # Prefer the richest recovery (most procedure/BZP/OPZ hits).
    extra = max(recovered, key=lambda t: len(_HAS_PROC_OR_BZP.findall(t)))
    logger.debug("Page %s: prepending higher-DPI referencyjny band OCR", index)
    # Prepend so "wobec … OPZ" / procedure numbers win over the damaged full-page OCR.
    page.text = f"{extra}\n{page.text.lstrip()}"
    page.lines = lines_from_plain_text(page.text)
    page.printable_chars, page.printable_ratio = printable_stats(page.text)
