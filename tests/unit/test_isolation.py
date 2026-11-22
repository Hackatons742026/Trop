"""A path problem with one PDF must not abort the whole batch."""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

import trop.orchestrator as orchestrator
from trop.orchestrator import process_case
from trop.settings import OcrSettings, Settings


def _pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Dokument testowy bez klasy, wystarczajaco dlugi tekst strony.")
    c.save()


def _settings() -> Settings:
    return Settings(ocr=OcrSettings(enabled=False), workers=1)


def test_symlinked_pdf_outside_input_is_processed(tmp_path: Path) -> None:
    real = tmp_path / "elsewhere" / "real.pdf"
    _pdf(real)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    try:
        (input_dir / "link.pdf").symlink_to(real)
    except OSError:
        pytest.skip("symlinks not supported here")

    result = process_case(input_dir, tmp_path / "output", workers=1, settings=_settings())

    assert result.failed == 0
    assert (tmp_path / "output" / "link.json").is_file()


def test_output_path_error_fails_only_that_file(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "input"
    _pdf(input_dir / "bad.pdf")
    _pdf(input_dir / "good.pdf")
    real_output_json_path = orchestrator.output_json_path

    def flaky(pdf: Path, in_dir: Path, out_dir: Path) -> Path:
        if pdf.name == "bad.pdf":
            raise ValueError("cannot mirror this path")
        return real_output_json_path(pdf, in_dir, out_dir)

    monkeypatch.setattr(orchestrator, "output_json_path", flaky)
    result = process_case(input_dir, tmp_path / "output", workers=1, settings=_settings())

    assert result.total == 2
    assert result.failed == 1
    assert (tmp_path / "output" / "good.json").is_file()
