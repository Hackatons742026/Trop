"""OCR fallback must not overwrite a genuine (if short) text layer."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import trop.ingest.text_layer as text_layer
from trop.ingest.pdf_backend import RenderedPage
from trop.models import TextSource
from trop.settings import OcrSettings

SIGNATURE_PAGE = "Warszawa, dnia 12.03.2026 r. Jan Nowak"  # 33 printable chars < 40
FULL_PAGE = "Odwołanie do Krajowej Izby Odwoławczej w sprawie zamówienia " * 5


class FakeBackend:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts

    def page_count(self) -> int:
        return len(self.texts)

    def page_size(self, index: int) -> tuple[float, float]:
        return 595.0, 842.0

    def extract_text(self, index: int) -> str:
        return self.texts[index]

    def render_page(self, index: int, dpi: int) -> RenderedPage:
        return RenderedPage(index, np.zeros((4, 4, 3), np.uint8), 595.0, 842.0)

    def close(self) -> None:
        pass


def _ingest(monkeypatch, texts: list[str], ocr_text: str, **ocr_kwargs):
    calls: list[int] = []

    def fake_ocr(image):
        calls.append(1)
        return ocr_text, []

    monkeypatch.setattr(text_layer, "ocr_image", fake_ocr)
    doc = text_layer.ingest_document(
        Path("x.pdf"), backend=FakeBackend(texts), ocr=OcrSettings(**ocr_kwargs)
    )
    return doc, calls


@pytest.mark.parametrize("ocr_text", ["", "Warszawa, dn1a 12.O3.2026 r. Jan Nowak"])
def test_short_text_layer_survives_weaker_ocr(monkeypatch, ocr_text: str) -> None:
    doc, calls = _ingest(monkeypatch, [SIGNATURE_PAGE], ocr_text)
    page = doc.pages[0]
    assert calls  # OCR was tried (page is under min_chars)
    assert page.text == SIGNATURE_PAGE
    assert page.source == TextSource.PDF_TEXT
    assert page.used_ocr is False


def test_ocr_wins_when_it_adds_a_page_of_text(monkeypatch) -> None:
    """A scan with a tiny text stamp: OCR reads the whole page."""
    doc, _ = _ingest(monkeypatch, ["Strona 1 z 5"], FULL_PAGE)
    assert doc.pages[0].text == FULL_PAGE
    assert doc.pages[0].source == TextSource.OCR
    assert doc.pages[0].used_ocr is True


def test_empty_text_layer_takes_any_ocr(monkeypatch) -> None:
    doc, _ = _ingest(monkeypatch, [""], "Krótki skan")
    assert doc.pages[0].text == "Krótki skan"
    assert doc.pages[0].source == TextSource.OCR


def test_discarded_ocr_attempts_count_against_budget(monkeypatch) -> None:
    _, calls = _ingest(monkeypatch, [SIGNATURE_PAGE] * 3, "", max_pages=1)
    assert len(calls) == 1
