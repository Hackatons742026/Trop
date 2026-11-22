"""TROP Streamlit GUI — upload PDFs, run the real pipeline, preview + download JSON.

Uses the same in-process path as the CLI (``process_one_pdf`` + ``write_json`` /
``write_empty_json``) so downloaded JSON is byte-identical to ``trop run`` output.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import streamlit as st
from PIL import Image

# Allow ``streamlit run app/gui.py`` from the repo root without an editable install.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from trop.classify.rules import OTHER  # noqa: E402
from trop.ingest.pdf_backend import PdfiumBackend  # noqa: E402
from trop.orchestrator import process_one_pdf  # noqa: E402
from trop.registry.loader import (  # noqa: E402
    clear_registry_cache,
    load_classes,
    load_negatives,
)
from trop.settings import clear_settings_cache, get_settings  # noqa: E402

PREVIEW_DPI = 110
MAX_PREVIEW_PAGES = 20
WORK_DIR_PREFIX = "trop_gui_"
# Work dirs of sessions that ended are swept after this many seconds.
STALE_WORK_DIR_S = 6 * 3600


def _safe_stem(name: str) -> str:
    """Keep a stable PDF stem for mirrored JSON naming (same-stem as CLI)."""
    stem = Path(name).stem.strip() or "upload"
    # Avoid path separators leaking from browser filenames.
    return stem.replace("/", "_").replace("\\", "_")


def _sweep_stale_work_dirs(*, now: float | None = None) -> None:
    """Delete GUI work dirs untouched for ``STALE_WORK_DIR_S`` (ended sessions)."""
    cutoff = (now if now is not None else time.time()) - STALE_WORK_DIR_S
    for path in Path(tempfile.gettempdir()).glob(f"{WORK_DIR_PREFIX}*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            continue


@st.cache_data(max_entries=32, show_spinner=False)
def _render_pdf_pages(pdf_path: Path, *, dpi: int = PREVIEW_DPI) -> tuple[list[Image.Image], int]:
    """Rasterize PDF pages via pypdfium2 (``PdfiumBackend``) → RGB PIL images.

    Cached: Streamlit reruns the script on every widget interaction, and each
    work dir path is unique, so the path is a safe cache key.
    """
    images: list[Image.Image] = []
    with PdfiumBackend(pdf_path) as backend:
        total = backend.page_count()
        n_pages = min(total, MAX_PREVIEW_PAGES)
        for index in range(n_pages):
            rendered = backend.render_page(index, dpi=dpi)
            images.append(Image.fromarray(rendered.image))
    return images, total


def _flatten_fields(payload: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Simple key/value rows for a nested JSON object (skip empty containers)."""
    rows: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, dict):
                rows.extend(_flatten_fields(value, path))
            elif isinstance(value, list):
                if not value:
                    rows.append((path, "[]"))
                else:
                    for i, item in enumerate(value):
                        rows.extend(_flatten_fields(item, f"{path}[{i}]"))
            else:
                rows.append((path, "" if value is None else str(value)))
    else:
        rows.append((prefix or "(value)", "" if payload is None else str(payload)))
    return rows


def _run_pipeline(uploads: list[Any], *, previous_work_dir: str | None = None) -> dict[str, Any]:
    """Persist uploads and process each PDF via the CLI pipeline helpers.

    Removes this session's previous batch dir and stale dirs of ended
    sessions, so a long-running GUI does not fill the disk.
    """
    if previous_work_dir and Path(previous_work_dir).name.startswith(WORK_DIR_PREFIX):
        shutil.rmtree(previous_work_dir, ignore_errors=True)
    _sweep_stale_work_dirs()

    clear_settings_cache()
    clear_registry_cache()
    settings = get_settings()
    classes = load_classes()
    negatives = load_negatives()
    labels = {spec.id: spec.label for spec in classes}

    work = Path(tempfile.mkdtemp(prefix=WORK_DIR_PREFIX))
    input_dir = work / "input"
    output_dir = work / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    used_names: set[str] = set()

    for upload in uploads:
        original_name = Path(upload.name).name
        stem = _safe_stem(original_name)
        filename = f"{stem}.pdf"
        # Disambiguate duplicate stems within one batch.
        if filename.casefold() in used_names:
            n = 2
            while f"{stem}_{n}.pdf".casefold() in used_names:
                n += 1
            filename = f"{stem}_{n}.pdf"
        used_names.add(filename.casefold())

        pdf_path = input_dir / filename
        pdf_bytes = upload.getvalue()
        pdf_path.write_bytes(pdf_bytes)

        _pdf, json_path, err, _document, class_id = process_one_pdf(
            pdf_path,
            input_dir=input_dir,
            output_dir=output_dir,
            dpi=settings.resolved_dpi(),
            ocr=settings.ocr,
            max_pages=settings.max_pages,
            classes=classes,
            negatives=negatives,
        )
        raw = (
            json_path.read_text(encoding="utf-8")
            if json_path is not None and json_path.is_file()
            else "{}\n"
        )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        results.append(
            {
                "name": original_name,
                "saved_name": filename,
                "pdf_path": str(pdf_path),
                "json_path": str(json_path) if json_path else None,
                "json_text": raw,
                "payload": payload,
                "class_id": class_id,
                "class_label": labels.get(class_id, class_id),
                "recognised": class_id != OTHER,
                "error": err,
            }
        )

    return {
        "work_dir": str(work),
        "results": results,
    }


def main() -> None:
    st.set_page_config(
        page_title="TROP — PDF → JSON",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("TROP")
    st.caption("Upload PDFs → classify + extract → same JSON as ``trop run``.")

    uploads = st.file_uploader(
        "PDF files",
        type=["pdf"],
        accept_multiple_files=True,
        help="One or more appeal / case PDFs. Analysis uses the real TROP pipeline.",
    )

    run = st.button("Run analysis", type="primary", disabled=not uploads)

    if run:
        if not uploads:
            st.warning("Upload at least one PDF first.")
        else:
            with st.spinner("Processing with TROP pipeline…"):
                previous = (st.session_state.get("trop_batch") or {}).get("work_dir")
                st.session_state["trop_batch"] = _run_pipeline(
                    list(uploads), previous_work_dir=previous
                )
                st.session_state["trop_selected"] = 0

    batch = st.session_state.get("trop_batch")
    if not batch or not batch.get("results"):
        st.info("Upload PDF(s) and click **Run analysis** to see preview and JSON.")
        return

    results: list[dict[str, Any]] = batch["results"]
    names = [r["name"] for r in results]
    selected = st.selectbox(
        "Document",
        options=list(range(len(names))),
        format_func=lambda i: names[i],
        index=min(st.session_state.get("trop_selected", 0), len(names) - 1),
        key="trop_doc_select",
    )
    st.session_state["trop_selected"] = selected
    item = results[selected]

    if item.get("error"):
        st.warning(f"Pipeline error (JSON still written as ``{{}}``): {item['error']}")

    if item["recognised"]:
        st.success(f"Detected class: **{item['class_label']}** (`{item['class_id']}`)")
        if item.get("payload") == {}:
            st.caption("Class matched, but extraction wrote `{}` (same as CLI).")
    else:
        st.warning("not recognised — output is `{}`")

    left, right = st.columns(2, gap="large")

    with left:
        st.subheader("PDF preview")
        try:
            pages, total_pages = _render_pdf_pages(Path(item["pdf_path"]))
        except Exception as exc:  # noqa: BLE001 — keep UI usable on bad PDFs
            st.error(f"Could not render PDF: {exc}")
            pages, total_pages = [], 0
        if not pages:
            st.caption("No pages to display.")
        else:
            total_hint = (
                f" (showing first {MAX_PREVIEW_PAGES} of {total_pages})"
                if total_pages > MAX_PREVIEW_PAGES
                else ""
            )
            st.caption(f"{len(pages)} page(s){total_hint}")
            for i, image in enumerate(pages):
                st.image(image, caption=f"Page {i + 1}", width="stretch")

    with right:
        st.subheader("JSON result")
        json_text: str = item["json_text"]
        download_name = Path(item["saved_name"]).with_suffix(".json").name
        json_file = Path(item["json_path"]) if item.get("json_path") else None
        download_bytes = (
            json_file.read_bytes()
            if json_file is not None and json_file.is_file()
            else json_text.encode("utf-8")
        )
        st.download_button(
            label="Download JSON",
            data=download_bytes,
            file_name=download_name,
            mime="application/json",
            type="primary",
        )
        st.code(json_text.rstrip("\n") or "{}", language="json")

        payload = item.get("payload")
        if isinstance(payload, dict) and payload:
            rows = _flatten_fields(payload)
            if rows:
                st.subheader("Fields")
                st.dataframe(
                    {"field": [r[0] for r in rows], "value": [r[1] for r in rows]},
                    hide_index=True,
                    width="stretch",
                )


if __name__ == "__main__":
    main()
