"""Pair HackNation ``dane/`` PDFs with their gold JSON and diff predictions.

Pairing rules (as shipped in the organisers' repo):
  - ``<stem>.json`` next to the PDF is its gold (``skany/**/NNNN.pdf``,
    ``przyklad_NN/odwolanie.pdf`` …);
  - ``potwierdzenie_przelewu.pdf`` is scored against ``przelew.json``;
  - anything else (``negatywne/**``, extra notices in a case folder) → ``{}``.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval.align import align_lists
from eval.score import is_absent, values_equal

TRANSFER_STEMS = ("potwierdzenie_przelewu", "przelew")


@dataclass(frozen=True)
class FieldDiff:
    path: str
    pred: Any
    gold: Any

    def __str__(self) -> str:
        return f"{self.path}: pred={self.pred!r} gold={self.gold!r}"


def gold_path_for(pdf: Path) -> Path | None:
    """Gold JSON for ``pdf``, or ``None`` when the expected output is ``{}``."""
    same = pdf.with_suffix(".json")
    if same.is_file():
        return same
    if pdf.stem.lower() in TRANSFER_STEMS:
        alt = pdf.parent / "przelew.json"
        if alt.is_file():
            return alt
    return None


def load_gold(pdf: Path) -> dict[str, Any]:
    path = gold_path_for(pdf)
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def iter_pdfs(dane_root: Path) -> list[Path]:
    return sorted(p for p in dane_root.rglob("*.pdf") if p.is_file())


def diff_fields(pred: Any, gold: Any, path: str = "") -> list[FieldDiff]:
    """Leaf mismatches under the eval rules (TN ignored, lists aligned by content)."""
    out: list[FieldDiff] = []
    _diff(pred, gold, path, out)
    return out


def _diff(pred: Any, gold: Any, path: str, out: list[FieldDiff]) -> None:
    if isinstance(pred, list) or isinstance(gold, list):
        pairs = align_lists(
            pred if isinstance(pred, list) else [],
            gold if isinstance(gold, list) else [],
        )
        for i, (p_item, g_item) in enumerate(pairs):
            _diff(p_item, g_item, f"{path}[{i}]", out)
        return
    if isinstance(pred, dict) or isinstance(gold, dict):
        p = pred if isinstance(pred, dict) else {}
        g = gold if isinstance(gold, dict) else {}
        for key in sorted(set(p) | set(g)):
            _diff(p.get(key), g.get(key), f"{path}.{key}" if path else key, out)
        return
    if is_absent(pred) and is_absent(gold):
        return
    if not is_absent(pred) and not is_absent(gold) and values_equal(pred, gold, path):
        return
    out.append(FieldDiff(path, pred, gold))


def _ingest_fingerprint() -> str:
    """Hash of the ingest code + OCR config: a change invalidates cached Documents."""
    src = Path(__file__).resolve().parents[1] / "src" / "trop"
    h = hashlib.sha1()
    for path in sorted((src / "ingest").rglob("*.py")):
        h.update(path.read_bytes())
    for name in ("settings.py", "models.py"):
        h.update((src / name).read_bytes())
    app_yaml = src.parents[1] / "config" / "app.yaml"
    if app_yaml.is_file():
        h.update(app_yaml.read_bytes())
    return h.hexdigest()[:12]


def load_document(pdf: Path, dane_root: Path, cache_dir: Path | None) -> Any:
    """Ingest ``pdf`` (OCR included), reusing a pickle cache keyed by PDF + ingest code."""
    from trop.ingest.text_layer import ingest_document
    from trop.settings import get_settings

    rel = pdf.relative_to(dane_root)
    cached: Path | None = None
    if cache_dir is not None:
        digest = hashlib.sha1(pdf.read_bytes()).hexdigest()[:12]
        cached = cache_dir / _ingest_fingerprint() / rel.parent / f"{pdf.stem}-{digest}.pkl"
        if cached.is_file():
            with cached.open("rb") as fh:
                return pickle.load(fh)
    cfg = get_settings()
    document = ingest_document(
        pdf,
        relative_path=rel,
        dpi=cfg.resolved_dpi(),
        ocr=cfg.ocr,
        max_pages=cfg.max_pages,
    )
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        with cached.open("wb") as fh:
            pickle.dump(document, fh)
    return document
