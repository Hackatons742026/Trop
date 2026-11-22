"""Tests for PDF discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from trop.io.discover import discover_pdfs, is_pdf_path


def test_discover_finds_nested_and_case_insensitive(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()
    (tmp_path / "keep.txt").write_text("nope", encoding="utf-8")
    (tmp_path / "Root.PDF").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "a" / "nested.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "a" / "b" / "Polish odwołanie.pdf").write_bytes(b"%PDF-1.4\n")

    found = discover_pdfs(tmp_path)
    names = {p.name for p in found}
    assert names == {"Root.PDF", "nested.pdf", "Polish odwołanie.pdf"}
    assert all(is_pdf_path(p) for p in found)


def test_discover_empty_dir(tmp_path: Path) -> None:
    assert discover_pdfs(tmp_path) == []


def test_discover_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_pdfs(tmp_path / "missing")


def test_discover_sorted_by_relative_path(tmp_path: Path) -> None:
    (tmp_path / "z.pdf").write_bytes(b"%PDF")
    (tmp_path / "a.pdf").write_bytes(b"%PDF")
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "b.pdf").write_bytes(b"%PDF")
    rels = [str(p.relative_to(tmp_path)) for p in discover_pdfs(tmp_path)]
    assert rels == sorted(rels, key=str.casefold)
