"""Discover PDF inputs and map them to mirrored JSON output paths."""

from __future__ import annotations

from pathlib import Path


def is_pdf_path(path: Path) -> bool:
    """Return True if path looks like a PDF by extension (case-insensitive)."""
    return path.is_file() and path.suffix.lower() == ".pdf"


def discover_pdfs(input_dir: Path) -> list[Path]:
    """Recursively find every ``*.pdf`` / ``*.PDF`` under ``input_dir``.

    Results are sorted by relative path for stable processing order.
    Non-PDF files are ignored. Empty directories yield an empty list.
    """
    root = input_dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    found: list[Path] = []
    for path in root.rglob("*"):
        if is_pdf_path(path):
            found.append(path)

    found.sort(key=lambda p: str(p.relative_to(root)).casefold())
    return found


def relative_pdf_path(pdf_path: Path, input_dir: Path) -> Path:
    """Return path of ``pdf_path`` relative to ``input_dir``."""
    return pdf_path.resolve().relative_to(input_dir.resolve())


def output_json_path(pdf_path: Path, input_dir: Path, output_dir: Path) -> Path:
    """Mirror relative PDF path under output; JSON name = PDF stem + ``.json``.

    Preserves spaces and non-ASCII (e.g. Polish) characters in the stem.
    Never renames files to document class names.
    """
    rel = relative_pdf_path(pdf_path, input_dir)
    json_name = rel.stem + ".json"
    return (output_dir.resolve() / rel.parent / json_name).resolve()
