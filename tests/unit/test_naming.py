"""Tests for same-stem JSON naming and path mirroring."""

from __future__ import annotations

from pathlib import Path

from trop.io.discover import output_json_path, relative_pdf_path


def test_output_json_preserves_stem_and_polish_chars(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    pdf = input_dir / "sprawy" / "Odwołanie nr 12.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")

    out = output_json_path(pdf, input_dir, output_dir)
    assert out.name == "Odwołanie nr 12.json"
    assert out.parent == (output_dir / "sprawy").resolve()
    # Never rename to a class / form name.
    assert "class" not in out.name.casefold()


def test_output_json_mirrors_relative_tree(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    pdf = input_dir / "2024" / "Q1" / "case.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")

    rel = relative_pdf_path(pdf, input_dir)
    assert rel == Path("2024") / "Q1" / "case.pdf"

    out = output_json_path(pdf, input_dir, output_dir)
    assert out == (output_dir / "2024" / "Q1" / "case.json").resolve()


def test_spaces_in_filename_preserved(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    pdf = input_dir / "my file name.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF")
    assert output_json_path(pdf, input_dir, output_dir).name == "my file name.json"
