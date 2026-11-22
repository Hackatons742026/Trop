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


def test_referencyjny_looks_broken() -> None:
    broken = (
        "Dotyczy:\npn. Title\", nr referencyjny:\nZ     e     ien\n"
        "Publicznych, ogłoszenie w TED nr 2026/S 224-429185"
    )
    assert text_layer._referencyjny_looks_broken(broken) is True
    ok = "nr referencyjny: ZP/12/2026, ogłoszenie nr 2026/BZP 00879135/03"
    assert text_layer._referencyjny_looks_broken(ok) is False


def test_band_refine_prepends_recovered_procedure_numbers(monkeypatch) -> None:
    """When full-page OCR eats ZP/BZP, a higher-DPI band recovery is prepended."""
    damaged = (
        "Dotyczy:\npn. Robota\", nr referencyjny:\nZ     e     ien\n"
        "Publicznych\nwnoszę odwołanie wobec:\na i as\n"
    )
    recovered = (
        "nr referencyjny: ZP/12/2026, ogłoszenie nr 2026/BZP 00879135/03\n"
        "wnoszę odwołanie wobec:\nPrzedmiotu Zamówienia (OPZ),\n"
    )
    calls: list[str] = []

    def fake_ocr(image):
        # First call = full page; later = bands.
        if not calls:
            calls.append("page")
            return damaged, []
        calls.append("band")
        return recovered, []

    monkeypatch.setattr(text_layer, "ocr_image", fake_ocr)
    doc = text_layer.ingest_document(
        Path("x.pdf"),
        backend=FakeBackend([""]),
        ocr=OcrSettings(),
    )
    text = doc.pages[0].text
    assert "ZP/12/2026" in text
    assert text.index("ZP/12/2026") < text.index("Z     e")
    assert any(c == "band" for c in calls)
