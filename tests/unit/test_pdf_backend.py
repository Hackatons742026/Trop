"""PdfiumBackend text contract."""

from __future__ import annotations

from pathlib import Path

from reportlab.pdfgen import canvas

from trop.ingest.pdf_backend import PdfiumBackend


def test_extract_text_uses_lf_line_breaks(tmp_path: Path) -> None:
    """PDFium returns CRLF; class patterns are written against ``\\n``."""
    pdf = tmp_path / "lines.pdf"
    c = canvas.Canvas(str(pdf))
    for i, line in enumerate(["Mocodawca:", ".....................", "Anna Nowak"]):
        c.drawString(72, 720 - i * 20, line)
    c.save()

    with PdfiumBackend(pdf) as backend:
        text = backend.extract_text(0)

    assert "\r" not in text
    assert text.split("\n") == ["Mocodawca:", ".....................", "Anna Nowak"]
