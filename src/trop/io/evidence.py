"""Evidence sidecars written outside ``output/`` (never scored).

Layout: ``evidence/<rel_parent>/<stem>.evidence.json`` mirroring the input tree.
Scorers that glob ``output/**/*.json`` never see these files.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from trop.io.discover import relative_pdf_path
from trop.io.writer import write_json
from trop.models import Document, FieldValue

logger = logging.getLogger(__name__)

QUOTE_MAX = 240


def evidence_json_path(
    pdf_path: Path,
    input_dir: Path,
    evidence_dir: Path,
) -> Path:
    """Mirror relative PDF path under evidence; name = stem + ``.evidence.json``."""
    rel = relative_pdf_path(pdf_path, input_dir)
    name = f"{rel.stem}.evidence.json"
    return (evidence_dir.resolve() / rel.parent / name).resolve()


def _clip_quote(text: str, *, max_len: int = QUOTE_MAX) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1] + "…"


def locate_value_on_pages(
    document: Document,
    value: Any,
    *,
    method: str = "rules",
    confidence: float | None = None,
) -> list[dict[str, Any]]:
    """Find ``value`` as a substring on ingested pages; return evidence hits."""
    if value is None or value == "" or isinstance(value, (list, dict, bool)):
        return []
    needle = str(value).strip()
    if len(needle) < 2:
        return []

    hits: list[dict[str, Any]] = []
    # Escape for literal search; allow flexible whitespace.
    pattern = re.escape(needle)
    pattern = pattern.replace(r"\ ", r"\s+")
    try:
        cre = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return []

    for page in document.pages:
        text = page.text or ""
        if not text:
            continue
        m = cre.search(text)
        if not m:
            continue
        start = max(0, m.start() - 40)
        end = min(len(text), m.end() + 40)
        quote = _clip_quote(text[start:end])
        bbox: list[float] | None = None
        # Prefer word bbox if any word overlaps the match span (OCR tokens).
        for line in page.lines:
            for word in line.words:
                if word.bbox and needle.lower() in (word.text or "").lower():
                    bbox = list(word.bbox)
                    break
            if bbox is not None:
                break
        hits.append(
            {
                "page": page.index,
                "quote": quote,
                "bbox": bbox,
                "method": method,
                "confidence": confidence,
            }
        )
        if len(hits) >= 3:
            break
    return hits


def build_evidence_payload(
    document: Document,
    *,
    class_id: str | None,
    fields: list[FieldValue] | None = None,
    method: str = "rules",
) -> dict[str, Any]:
    """Assemble sidecar JSON (source + per-field evidence)."""
    items: list[dict[str, Any]] = []
    field_list = fields
    if field_list is None:
        field_list = list(document.__dict__.get("_extracted_fields") or [])

    for fv in field_list:
        ev = list(fv.evidence) if fv.evidence else []
        if not ev and fv.value is not None and fv.value != "":
            ev = locate_value_on_pages(
                document,
                fv.value,
                method=method,
                confidence=fv.conf,
            )
        items.append(
            {
                "name": fv.name,
                "value": fv.value,
                "evidence": ev,
            }
        )

    return {
        "source": document.relative_path.as_posix(),
        "class_id": class_id,
        "fields": items,
    }


def write_evidence_sidecar(
    evidence_dir: Path,
    pdf_path: Path,
    input_dir: Path,
    document: Document,
    *,
    class_id: str | None,
    fields: list[FieldValue] | None = None,
    method: str = "rules",
) -> Path:
    """Write ``*.evidence.json`` under ``evidence_dir`` (outside output/)."""
    path = evidence_json_path(pdf_path, input_dir, evidence_dir)
    payload = build_evidence_payload(
        document,
        class_id=class_id,
        fields=fields,
        method=method,
    )
    write_json(path, payload)
    logger.debug("Wrote evidence sidecar: %s", path)
    return path
