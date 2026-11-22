"""Submission-grade PDF E2E: reportlab text PDFs → schema-valid scored JSON."""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from trop.io.schema_validate import validate_payload
from trop.orchestrator import process_case
from trop.registry.loader import clear_registry_cache, load_classes
from trop.settings import OcrSettings, Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "text"

# Helvetica lacks Polish glyphs; register a Unicode TTF for the text layer.
_FONT_NAME = "TROPUnicode"
_FONT_REGISTERED = False
_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path(r"C:\Windows\Fonts\calibri.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
)


def setup_function() -> None:
    clear_registry_cache()


def _ensure_unicode_font() -> str:
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return _FONT_NAME
    for candidate in _FONT_CANDIDATES:
        if candidate.is_file():
            pdfmetrics.registerFont(TTFont(_FONT_NAME, str(candidate)))
            _FONT_REGISTERED = True
            return _FONT_NAME
    raise FileNotFoundError(
        "No Unicode TTF found for PDF E2E (tried Arial/Calibri/DejaVu/Liberation)"
    )


def _write_multiline_pdf(path: Path, text: str) -> None:
    """Embed clear printable Unicode text (text-layer PDF; OCR not required)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    font = _ensure_unicode_font()
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(font, 11)
    y = 800
    for line in text.splitlines():
        if not line.strip():
            y -= 14
            continue
        c.drawString(40, y, line[:110])
        y -= 14
        if y < 40:
            c.showPage()
            c.setFont(font, 11)
            y = 800
    c.save()


def _settings() -> Settings:
    return Settings(ocr=OcrSettings(enabled=False), workers=1, evidence_dir=None)


def test_pdf_e2e_przelew_writes_schema_valid_json(tmp_path: Path) -> None:
    text = (FIXTURES / "przelew_smoke.txt").read_text(encoding="utf-8")
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _write_multiline_pdf(input_dir / "przelew_case.pdf", text)

    result = process_case(input_dir, output_dir, workers=1, settings=_settings())
    assert result.total == 1
    assert result.failed == 0
    out = output_dir / "przelew_case.json"
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload != {}
    assert "przelew_bankowy" in payload
    spec = next(s for s in load_classes() if s.id == "przelew")
    assert validate_payload(payload, spec.schema)


def test_pdf_e2e_odwolanie_writes_schema_valid_json(tmp_path: Path) -> None:
    text = (FIXTURES / "odwolanie_smoke.txt").read_text(encoding="utf-8")
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _write_multiline_pdf(input_dir / "odwolanie_case.pdf", text)

    result = process_case(input_dir, output_dir, workers=1, settings=_settings())
    assert result.total == 1
    out = output_dir / "odwolanie_case.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload != {}
    assert payload.get("OdwolanieKIO", {}).get("czynnosc_powod_id") == 1
    spec = next(s for s in load_classes() if s.id == "odwolanie")
    assert validate_payload(payload, spec.schema)


def test_no_evidence_sidecars_without_flag(tmp_path: Path) -> None:
    text = (FIXTURES / "przelew_smoke.txt").read_text(encoding="utf-8")
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    _write_multiline_pdf(input_dir / "x.pdf", text)

    process_case(
        input_dir,
        output_dir,
        evidence_dir=None,
        workers=1,
        settings=_settings(),
    )
    assert list(evidence_dir.rglob("*.evidence.json")) == []
