"""Streamlit GUI: renders, and does not leak per-batch work dirs."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

from app import gui  # noqa: E402

GUI = Path(__file__).resolve().parents[2] / "app" / "gui.py"


class _Upload:
    def __init__(self, path: Path) -> None:
        self.name = path.name
        self._data = path.read_bytes()

    def getvalue(self) -> bytes:
        return self._data


def _pdf(path: Path) -> Path:
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Dokument testowy dla GUI, wystarczajaco dlugi tekst.")
    c.save()
    return path


def test_gui_renders_empty_state() -> None:
    at = AppTest.from_file(str(GUI)).run(timeout=60)
    assert not at.exception
    assert any("Run analysis" in i.value for i in at.info)


def test_new_batch_removes_previous_work_dir(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gui.tempfile, "tempdir", str(tmp_path))
    upload = _Upload(_pdf(tmp_path / "a.pdf"))

    first = gui._run_pipeline([upload])
    assert Path(first["work_dir"]).is_dir()
    assert first["results"][0]["error"] is None
    pdf_path = Path(first["results"][0]["pdf_path"])
    images, total = gui._render_pdf_pages(pdf_path)
    assert total == 1 and len(images) == 1
    assert gui._render_pdf_pages(pdf_path)[1] == 1  # cached call

    second = gui._run_pipeline([upload], previous_work_dir=first["work_dir"])
    assert not Path(first["work_dir"]).exists()
    assert Path(second["work_dir"]).is_dir()


def test_stale_work_dirs_are_swept(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gui.tempfile, "tempdir", str(tmp_path))
    stale = tmp_path / f"{gui.WORK_DIR_PREFIX}old"
    fresh = tmp_path / f"{gui.WORK_DIR_PREFIX}new"
    other = tmp_path / "unrelated_old"
    for d in (stale, fresh, other):
        d.mkdir()
    old = time.time() - gui.STALE_WORK_DIR_S - 60
    os.utime(stale, (old, old))
    os.utime(other, (old, old))

    gui._sweep_stale_work_dirs()

    assert not stale.exists()
    assert fresh.exists()
    assert other.exists()
