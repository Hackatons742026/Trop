"""Golden tests: every PDF under the organisers' ``dane/`` must reproduce its gold JSON.

``TROP_DANE_DIR`` points at the data (default ``<repo>/dane``); the module is
skipped when it is absent. Ingested Documents are cached under
``.cache/golden`` so reruns only pay for classify + extract.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from eval.dane import diff_fields, iter_pdfs, load_document, load_gold
from trop.registry.loader import load_classes, load_negatives

ROOT = Path(__file__).resolve().parents[2]
DANE = Path(os.environ.get("TROP_DANE_DIR", ROOT / "dane"))
CACHE = ROOT / ".cache" / "golden"

PDFS = iter_pdfs(DANE) if DANE.is_dir() else []

pytestmark = pytest.mark.skipif(not PDFS, reason=f"no golden PDFs under {DANE}")


@pytest.mark.parametrize(
    "pdf",
    PDFS,
    ids=[p.relative_to(DANE).as_posix() for p in PDFS],
)
def test_dane_document_matches_gold(pdf: Path) -> None:
    from trop.orchestrator import build_payload

    document = load_document(pdf, DANE, CACHE)
    _class_id, payload = build_payload(
        document,
        classes=load_classes(),
        negatives=load_negatives(),
    )
    gold = load_gold(pdf)
    if gold == {}:
        assert payload == {}, f"expected {{}}, got class with keys {sorted(payload)}"
        return
    assert payload, "expected a classified document, got {}"
    diffs = diff_fields(payload, gold)
    assert not diffs, "\n".join(str(d) for d in diffs)
