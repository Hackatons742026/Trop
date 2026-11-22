"""Evidence sidecars live outside output/ and are never scored with output globs."""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from trop.io.evidence import (
    build_evidence_payload,
    evidence_json_path,
    locate_value_on_pages,
    write_evidence_sidecar,
)
from trop.models import Document, FieldValue, Page, TextSource
from trop.orchestrator import process_case

_FONT = "TROPArialEvidence"
_FONT_PATHS = (
    Path(r"C:\Windows\Fonts\arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
)


def _make_text_pdf(path: Path, text: str) -> None:
    if _FONT not in pdfmetrics.getRegisteredFontNames():
        for font_path in _FONT_PATHS:
            if font_path.is_file():
                pdfmetrics.registerFont(TTFont(_FONT, str(font_path)))
                break
    c = canvas.Canvas(str(path))
    if _FONT in pdfmetrics.getRegisteredFontNames():
        c.setFont(_FONT, 11)
    c.drawString(72, 720, text[:80])
    c.save()


def test_evidence_json_path_mirrors_rel(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    ev_dir = tmp_path / "evidence"
    pdf = input_dir / "skany" / "odwolania" / "0001" / "0001.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4")
    out = evidence_json_path(pdf, input_dir, ev_dir)
    assert out == (ev_dir / "skany" / "odwolania" / "0001" / "0001.evidence.json").resolve()


def test_locate_and_write_sidecar(tmp_path: Path) -> None:
    doc = Document(
        path=tmp_path / "a.pdf",
        relative_path=Path("case/a.pdf"),
        pages=[
            Page(
                index=0,
                text="Kwota 1234.56 PLN przelew tytuł TEST",
                source=TextSource.PDF_TEXT,
            )
        ],
    )
    hits = locate_value_on_pages(doc, "1234.56", method="rules", confidence=0.9)
    assert hits
    assert hits[0]["page"] == 0
    assert "1234.56" in hits[0]["quote"]
    assert hits[0]["method"] == "rules"
    assert "bbox" in hits[0]
    assert "confidence" in hits[0]

    fields = [
        FieldValue(name="przelew_bankowy.kwota", value="1234.56", evidence=hits),
        FieldValue(name="missing", value=None),
    ]
    payload = build_evidence_payload(doc, class_id="przelew", fields=fields)
    assert payload["source"] == "case/a.pdf"
    assert payload["class_id"] == "przelew"
    assert payload["fields"][0]["evidence"][0]["page"] == 0

    pdf = tmp_path / "in" / "case" / "a.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    ev = write_evidence_sidecar(
        tmp_path / "evidence",
        pdf,
        tmp_path / "in",
        doc,
        class_id="przelew",
        fields=fields,
    )
    assert ev.name == "a.evidence.json"
    data = json.loads(ev.read_text(encoding="utf-8"))
    assert data["fields"][0]["name"] == "przelew_bankowy.kwota"


def test_extracted_fields_feed_evidence(tmp_path: Path) -> None:
    from trop.extract.engine import extract_document
    from trop.registry.loader import load_classes

    text = (Path(__file__).resolve().parents[1] / "fixtures/text/przelew_smoke.txt").read_text(
        encoding="utf-8"
    )
    doc = Document(
        path=tmp_path / "p.pdf",
        relative_path=Path("p.pdf"),
        pages=[Page(index=0, text=text, source=TextSource.PDF_TEXT)],
    )
    spec = next(s for s in load_classes() if s.id == "przelew")
    extract_document(doc, spec)

    by_name = {f.name: f.value for f in doc.fields}
    assert by_name["przelew_bankowy.numer_transakcji"] == "CEN2609035760798"
    payload = build_evidence_payload(doc, class_id="przelew")
    hit = next(f for f in payload["fields"] if f["name"] == "przelew_bankowy.numer_transakcji")
    assert hit["evidence"] and hit["evidence"][0]["page"] == 0


def test_orchestrator_evidence_outside_output(tmp_path: Path) -> None:
    from trop.settings import OcrSettings, Settings

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    evidence_dir = tmp_path / "evidence"
    nested = input_dir / "folder"
    nested.mkdir(parents=True)
    _make_text_pdf(nested / "sample.pdf", "To nie jest odwolanie ani przelew.")

    # OCR off: avoid raster path; still exercises evidence wiring for OOC {}.
    settings = Settings(ocr=OcrSettings(enabled=False), workers=1)
    result = process_case(
        input_dir,
        output_dir,
        evidence_dir=evidence_dir,
        workers=1,
        settings=settings,
    )
    assert result.total == 1
    scored = list(output_dir.rglob("*.json"))
    assert len(scored) == 1
    assert scored[0].name == "sample.json"
    # Scorer-style glob on output must not see evidence.
    assert not any(p.name.endswith(".evidence.json") for p in scored)

    sidecars = list(evidence_dir.rglob("*.evidence.json"))
    assert len(sidecars) == 1
    assert sidecars[0].name == "sample.evidence.json"
    assert sidecars[0].is_relative_to(evidence_dir)
    assert not sidecars[0].is_relative_to(output_dir)
