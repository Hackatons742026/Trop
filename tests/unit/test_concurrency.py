"""PDFium is not thread-safe: ``workers > 1`` must not crash the process.

Without the process-wide PDFium lock these tests abort the interpreter
(SIGABRT / SIGSEGV) instead of failing an assertion.
"""

from __future__ import annotations

import threading
from pathlib import Path

from reportlab.pdfgen import canvas

from trop.ingest.pdf_backend import PdfiumBackend
from trop.orchestrator import process_case
from trop.settings import OcrSettings, Settings


def _write_pdf(path: Path, pages: int = 6) -> None:
    c = canvas.Canvas(str(path))
    for page in range(pages):
        for line in range(40):
            c.drawString(40, 800 - line * 18, f"Strona {page} linia {line} tekst testowy")
        c.showPage()
    c.save()


def test_parallel_workers_do_not_crash(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    for i in range(24):
        _write_pdf(input_dir / f"case_{i:02d}.pdf")

    settings = Settings(ocr=OcrSettings(enabled=False), workers=4)
    result = process_case(input_dir, output_dir, workers=4, settings=settings)

    assert result.total == 24
    assert result.failed == 0
    assert len(list(output_dir.glob("*.json"))) == 24


def test_backend_render_from_many_threads(tmp_path: Path) -> None:
    pdfs = []
    for i in range(4):
        path = tmp_path / f"doc{i}.pdf"
        _write_pdf(path, pages=4)
        pdfs.append(path)

    errors: list[BaseException] = []

    def work(i: int) -> None:
        try:
            for _ in range(10):
                with PdfiumBackend(pdfs[i % len(pdfs)]) as backend:
                    for k in range(backend.page_count()):
                        backend.page_size(k)
                        backend.extract_text(k)
                        backend.render_page(k, dpi=72)
        except BaseException as exc:  # noqa: BLE001 — surface in the main thread
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
