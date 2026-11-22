"""Case orchestrator: discover → ingest → classify → extract → normalize → write.

OOC / look-alikes / errors → exactly ``{}``. Output filenames stay PDF-stem based.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trop.classify.rules import OTHER, classify_document
from trop.extract.blocks import document_text
from trop.extract.engine import extract_document
from trop.ingest.text_layer import ingest_document
from trop.io.discover import discover_pdfs, output_json_path, relative_pdf_path
from trop.io.evidence import write_evidence_sidecar
from trop.io.schema_validate import validated_or_empty
from trop.io.writer import write_empty_json, write_json
from trop.llm import maybe_assist
from trop.models import Document
from trop.registry.loader import ClassSpec, load_classes, load_negatives
from trop.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class ProcessResult:
    """Summary of a case run."""

    input_dir: Path
    output_dir: Path
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    classified: dict[str, int] = field(default_factory=dict)
    outputs: list[Path] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)


def _class_index(specs: tuple[ClassSpec, ...]) -> dict[str, ClassSpec]:
    return {s.id: s for s in specs}


def _maybe_write_evidence(
    evidence_dir: Path | None,
    pdf: Path,
    input_dir: Path,
    document: Document | None,
    class_id: str,
) -> None:
    """Write evidence sidecar outside output/; never touches scored JSON."""
    if evidence_dir is None or document is None:
        return
    try:
        write_evidence_sidecar(
            evidence_dir,
            pdf,
            input_dir,
            document,
            class_id=class_id,
        )
    except Exception as exc:  # noqa: BLE001 — evidence is optional
        logger.warning("Evidence sidecar failed for %s: %s", pdf, exc)


def process_one_pdf(
    pdf: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    dpi: int,
    ocr: Any,
    classes: tuple[ClassSpec, ...],
    negatives: Any,
    max_pages: int | None = 40,
    evidence_dir: Path | None = None,
) -> tuple[Path, Path | None, str | None, Document | None, str]:
    """Process a single PDF → JSON. Returns (pdf, json_path, err, document, class_id)."""
    json_path: Path | None = None
    class_id = OTHER
    try:
        # Inside the try: a path error must fail this file, not the batch.
        json_path = output_json_path(pdf, input_dir, output_dir)
        rel = relative_pdf_path(pdf, input_dir)
        document = ingest_document(
            pdf,
            relative_path=rel,
            dpi=dpi,
            ocr=ocr,
            max_pages=max_pages,
        )
        result = classify_document(document, classes=classes, negatives=negatives)
        class_id = result.class_id
        by_id = _class_index(classes)
        if class_id == OTHER or class_id not in by_id:
            write_empty_json(json_path)
            document.doc_class = OTHER
            _maybe_write_evidence(evidence_dir, pdf, input_dir, document, OTHER)
            return pdf, json_path, None, document, OTHER

        spec = by_id[class_id]
        payload = extract_document(document, spec)
        # Optional LLM assist (profile none / missing key → payload unchanged).
        payload = maybe_assist(
            payload,
            document_text=document_text([p.text for p in document.pages]),
            class_id=class_id,
        )
        # Schema-valid null-filled objects only; invalid → {}.
        payload = validated_or_empty(payload, spec.schema, validator=spec.validator)
        if not payload:
            write_empty_json(json_path)
            _maybe_write_evidence(evidence_dir, pdf, input_dir, document, class_id)
            return pdf, json_path, None, document, class_id
        write_json(json_path, payload)
        _maybe_write_evidence(evidence_dir, pdf, input_dir, document, class_id)
        return pdf, json_path, None, document, class_id
    except Exception as exc:  # noqa: BLE001 — isolate per file
        logger.exception("Failed processing %s: %s", pdf, exc)
        if json_path is not None:
            try:
                write_empty_json(json_path)
            except Exception as write_exc:  # noqa: BLE001
                logger.error("Could not write {} for %s: %s", pdf, write_exc)
        return pdf, json_path, str(exc), None, OTHER


def process_case(
    input_dir: Path | str,
    output_dir: Path | str,
    *,
    evidence_dir: Path | str | None = None,
    workers: int | None = None,
    settings: Settings | None = None,
) -> ProcessResult:
    """Process every PDF under ``input_dir`` into mirrored JSON under ``output_dir``.

    Per-file isolation: a crash on one PDF writes ``{}``, logs the error, and
    continues. Exit status is decided by the CLI (0 if input exists).
    """
    cfg = settings or get_settings()
    in_dir = Path(input_dir)
    out_dir = Path(output_dir)
    # Caller (CLI) passes --evidence or config paths.evidence_dir; None = skip.
    ev_dir = Path(evidence_dir) if evidence_dir else None
    n_workers = workers if workers is not None else cfg.resolved_workers()

    if not in_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {in_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)
    if ev_dir is not None:
        ev_dir.mkdir(parents=True, exist_ok=True)

    classes = load_classes()
    negatives = load_negatives()
    pdfs = discover_pdfs(in_dir)
    result = ProcessResult(input_dir=in_dir, output_dir=out_dir, total=len(pdfs))

    if not pdfs:
        logger.info("No PDFs found under %s", in_dir)
        return result

    logger.info(
        "Processing %s PDF(s) with %s worker(s); classes=%s",
        len(pdfs),
        n_workers,
        [c.id for c in classes],
    )

    dpi = cfg.resolved_dpi()

    def _one(pdf: Path) -> tuple[Path, Path | None, str | None, Document | None, str]:
        return process_one_pdf(
            pdf,
            input_dir=in_dir,
            output_dir=out_dir,
            dpi=dpi,
            ocr=cfg.ocr,
            max_pages=cfg.max_pages,
            classes=classes,
            negatives=negatives,
            evidence_dir=ev_dir,
        )

    if n_workers <= 1:
        for pdf in pdfs:
            pdf, json_path, err, _document, class_id = _one(pdf)
            _record(result, pdf, json_path, err, class_id)
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_one, pdf): pdf for pdf in pdfs}
            for fut in as_completed(futures):
                pdf, json_path, err, _document, class_id = fut.result()
                _record(result, pdf, json_path, err, class_id)

    logger.info(
        "Done: %s ok, %s failed, %s total → %s | classes=%s",
        result.succeeded,
        result.failed,
        result.total,
        out_dir,
        result.classified,
    )
    return result


def _record(
    result: ProcessResult,
    pdf: Path,
    json_path: Path | None,
    err: str | None,
    class_id: str,
) -> None:
    # Documents (full page text) are not retained: memory stays flat per run.
    result.classified[class_id] = result.classified.get(class_id, 0) + 1
    if json_path is not None:
        result.outputs.append(json_path)
    if err:
        result.failed += 1
        result.errors.append((pdf, err))
    else:
        result.succeeded += 1
