"""Core domain models for ingested PDF cases.

Ingest populates Document/Page text; classify + extract fill doc_class / fields.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class TextSource(StrEnum):
    """Where page text came from."""

    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    MIXED = "mixed"
    EMPTY = "empty"


class Word(BaseModel):
    """A single word (or OCR token) with optional bounding box."""

    text: str
    conf: float | None = None
    # Normalized page coords [0,1] or PDF canvas units — unset in P0 when unknown.
    bbox: tuple[float, float, float, float] | None = None


class Line(BaseModel):
    """A line of text composed of words."""

    text: str
    words: list[Word] = Field(default_factory=list)
    conf: float | None = None
    bbox: tuple[float, float, float, float] | None = None


class FieldValue(BaseModel):
    """Extracted form field; evidence lives in sidecars, never in scored JSON."""

    name: str
    value: Any = None
    conf: float | None = None
    source: TextSource | None = None
    # page / quote / bbox / method / confidence — written to evidence/*.evidence.json
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class Page(BaseModel):
    """One PDF page after text-layer and/or OCR ingest."""

    index: int
    width: float | None = None
    height: float | None = None
    text: str = ""
    lines: list[Line] = Field(default_factory=list)
    source: TextSource = TextSource.EMPTY
    printable_chars: int = 0
    printable_ratio: float = 0.0
    used_ocr: bool = False


class Document(BaseModel):
    """A single PDF file as discovered on disk."""

    path: Path
    relative_path: Path
    page_count: int = 0
    pages: list[Page] = Field(default_factory=list)
    # Document class (form type) — assigned in classify step (P1).
    doc_class: str | None = None
    error: str | None = None


class Case(BaseModel):
    """A processing case: one input tree run producing mirrored JSON outputs."""

    input_dir: Path
    output_dir: Path
    evidence_dir: Path | None = None
    documents: list[Document] = Field(default_factory=list)
