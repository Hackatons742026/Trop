"""Tests for JSON writer (empty object contract)."""

from __future__ import annotations

import json
from pathlib import Path

from trop.io.writer import read_json_object, write_empty_json, write_json
from trop.orchestrator import process_case


def test_write_empty_json_is_exactly_object(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "out.json"
    write_empty_json(path)
    raw = path.read_text(encoding="utf-8").strip()
    assert raw == "{}"
    assert json.loads(raw) == {}


def test_write_json_preserves_unicode(tmp_path: Path) -> None:
    path = tmp_path / "pl.json"
    write_json(path, {"imię": "Łukasz", "nr": "12"})
    data = read_json_object(path)
    assert data["imię"] == "Łukasz"
    assert "Łukasz" in path.read_text(encoding="utf-8")


def test_corrupt_pdf_pipeline_writes_empty(tmp_path: Path) -> None:
    """Corrupt ``.pdf`` still yields ``{}`` (per-file isolation)."""
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    bad = input_dir / "broken.pdf"
    bad.write_bytes(b"this is not a pdf at all")

    result = process_case(input_dir, output_dir, workers=1)
    assert result.total == 1
    assert result.failed == 1
    out = output_dir / "broken.json"
    assert out.is_file()
    assert out.read_text(encoding="utf-8").strip() == "{}"
