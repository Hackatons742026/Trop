"""Micro-F1 scoring: exact leaves + 80% similarity for long-string fields; TN ignored."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from eval.align import align_lists

# Long-string fields: >= 80% similarity counts as TP (mentor rule).
LONG_STRING_SUFFIXES = (
    "pelnomocnik.nazwa",  # attorney company name
    "przelew_bankowy.tytul",  # transfer title
    "Odwolujacy.nazwa",  # appellant name (path contains)
    "Zamawiajacy.nazwa",  # authority name
    "ZamowieniePubliczne.tytul",  # contract title
    "mocodawca.data.nazwa",
    ".nazwa",  # broad: company/person display names in lists
    ".tytul",
)

# Paths ending with these use fuzzy match when both are non-empty strings.
_FUZZY_KEYS = {
    "nazwa",
    "tytul",
}

HOLD_OUT_MIN = 46
HOLD_OUT_MAX = 60
HOLD_OUT_RE = re.compile(r"przyklad_(\d+)", re.IGNORECASE)

SIMILARITY_THRESHOLD = 80.0


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def merge(self, other: Counts) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


@dataclass
class DocScore:
    rel_path: str
    counts: Counts
    holdout: bool = False
    empty_match: bool | None = None  # True if both {}, False if mismatch empties
    notes: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    docs: list[DocScore] = field(default_factory=list)
    total: Counts = field(default_factory=Counts)
    train: Counts = field(default_factory=Counts)
    holdout: Counts = field(default_factory=Counts)
    # Hold-out case range actually used (gold_map.yaml may override it).
    holdout_min: int = HOLD_OUT_MIN
    holdout_max: int = HOLD_OUT_MAX

    def to_dict(self) -> dict[str, Any]:
        return {
            "micro_f1": round(self.total.f1, 4),
            "precision": round(self.total.precision, 4),
            "recall": round(self.total.recall, 4),
            "tp": self.total.tp,
            "fp": self.total.fp,
            "fn": self.total.fn,
            "train": {
                "f1": round(self.train.f1, 4),
                "tp": self.train.tp,
                "fp": self.train.fp,
                "fn": self.train.fn,
            },
            "holdout": {
                "f1": round(self.holdout.f1, 4),
                "tp": self.holdout.tp,
                "fp": self.holdout.fp,
                "fn": self.holdout.fn,
                "case_range": f"{self.holdout_min}-{self.holdout_max}",
                "note": f"cases {self.holdout_min}..{self.holdout_max} flagged as hold-out",
            },
            "documents": [
                {
                    "path": d.rel_path,
                    "holdout": d.holdout,
                    "f1": round(d.counts.f1, 4),
                    "tp": d.counts.tp,
                    "fp": d.counts.fp,
                    "fn": d.counts.fn,
                    "empty_match": d.empty_match,
                    "notes": d.notes,
                }
                for d in self.docs
            ],
        }


def is_absent(value: Any) -> bool:
    """TN rule: both absent (null / missing / empty string) are not counted."""
    if value is None:
        return True
    if value == "":
        return True
    return False


def is_holdout_path(
    rel: str | Path,
    *,
    case_min: int = HOLD_OUT_MIN,
    case_max: int = HOLD_OUT_MAX,
    pattern: re.Pattern[str] | str | None = None,
) -> bool:
    """True if the case number captured by ``pattern`` (group 1) is in range."""
    if pattern is None:
        rx = HOLD_OUT_RE
    elif isinstance(pattern, str):
        rx = re.compile(pattern, re.IGNORECASE)
    else:
        rx = pattern
    m = rx.search(str(rel).replace("\\", "/"))
    if not m:
        return False
    n = int(m.group(1))
    return case_min <= n <= case_max


def _use_fuzzy(path: str) -> bool:
    leaf = path.split(".")[-1].split("[")[0]
    if leaf in _FUZZY_KEYS:
        return True
    for suffix in LONG_STRING_SUFFIXES:
        if path.endswith(suffix) or suffix in path:
            return True
    return False


def values_equal(pred: Any, gold: Any, path: str) -> bool:
    if isinstance(pred, (int, float)) and isinstance(gold, (int, float)):
        return float(pred) == float(gold)
    if isinstance(pred, str) and isinstance(gold, str):
        if _use_fuzzy(path):
            # Normalized edit-distance similarity. Not token_set_ratio: it
            # scores 100 whenever one side's tokens are a subset of the
            # other's ("Gmina" vs "Gmina Miejska Kraków"), hiding over- and
            # under-capture and inflating F1.
            return fuzz.ratio(pred, gold) >= SIMILARITY_THRESHOLD
        return pred == gold
    return pred == gold


def score_leaves(pred: Any, gold: Any, path: str = "") -> Counts:
    """Recursively score aligned structures."""
    counts = Counts()

    # Both absent at this leaf
    if not isinstance(pred, (dict, list)) and not isinstance(gold, (dict, list)):
        if is_absent(pred) and is_absent(gold):
            return counts  # TN — ignore
        if is_absent(pred) and not is_absent(gold):
            counts.fn += 1
            return counts
        if not is_absent(pred) and is_absent(gold):
            counts.fp += 1
            return counts
        if values_equal(pred, gold, path):
            counts.tp += 1
        else:
            counts.fp += 1
            counts.fn += 1
        return counts

    if isinstance(gold, list) or isinstance(pred, list):
        pred_list = pred if isinstance(pred, list) else []
        gold_list = gold if isinstance(gold, list) else []
        pairs = align_lists(pred_list, gold_list)
        for i, (p_item, g_item) in enumerate(pairs):
            child = f"{path}[{i}]"
            if p_item is None and g_item is not None:
                counts.merge(score_leaves(None, g_item, child))
            elif p_item is not None and g_item is None:
                counts.merge(score_leaves(p_item, None, child))
            else:
                counts.merge(score_leaves(p_item, g_item, child))
        return counts

    if isinstance(gold, dict) or isinstance(pred, dict):
        p = pred if isinstance(pred, dict) else {}
        g = gold if isinstance(gold, dict) else {}
        keys = set(p) | set(g)
        for key in sorted(keys):
            child = f"{path}.{key}" if path else key
            counts.merge(score_leaves(p.get(key), g.get(key), child))
        return counts

    return counts


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_gold_map(path: Path | None) -> dict[str, Any]:
    if path is None:
        default = Path(__file__).resolve().parent / "gold_map.yaml"
        path = default if default.is_file() else None
    if path is None or not Path(path).is_file():
        return {"mappings": {}, "holdout": {"case_min": HOLD_OUT_MIN, "case_max": HOLD_OUT_MAX}}
    with Path(path).open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def iter_json_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.json") if p.is_file())


def resolve_gold_path(
    pred_path: Path,
    pred_root: Path,
    gold_root: Path,
    mappings: dict[str, str],
) -> Path:
    rel = pred_path.relative_to(pred_root).as_posix()
    mapped = mappings.get(rel) or mappings.get(str(pred_path.as_posix()))
    if mapped:
        return gold_root / mapped
    return gold_root / rel


def evaluate(
    pred_dir: Path | str,
    gold_dir: Path | str,
    *,
    map_path: Path | str | None = None,
) -> EvalReport:
    pred_root = Path(pred_dir)
    gold_root = Path(gold_dir)
    meta = load_gold_map(Path(map_path) if map_path else None)
    mappings = {str(k): str(v) for k, v in (meta.get("mappings") or {}).items()}
    hold = meta.get("holdout") or {}
    case_min = int(hold.get("case_min", HOLD_OUT_MIN))
    case_max = int(hold.get("case_max", HOLD_OUT_MAX))
    hold_rx = re.compile(hold["pattern"], re.IGNORECASE) if hold.get("pattern") else HOLD_OUT_RE

    def holdout_of(rel: str) -> bool:
        return is_holdout_path(rel, case_min=case_min, case_max=case_max, pattern=hold_rx)

    report = EvalReport(holdout_min=case_min, holdout_max=case_max)
    matched_gold: set[Path] = set()

    for pred_path in iter_json_files(pred_root):
        rel = pred_path.relative_to(pred_root).as_posix()
        gold_path = resolve_gold_path(pred_path, pred_root, gold_root, mappings)
        holdout = holdout_of(rel)
        notes: list[str] = []
        if holdout:
            notes.append("hold-out")

        if not gold_path.is_file():
            notes.append("missing gold")
            # Treat entire pred as FP leaves — load pred and score against {}
            pred_obj = load_json(pred_path)
            counts = score_leaves(pred_obj, {})
            doc = DocScore(rel_path=rel, counts=counts, holdout=holdout, notes=notes)
            report.docs.append(doc)
            report.total.merge(counts)
            (report.holdout if holdout else report.train).merge(counts)
            continue

        matched_gold.add(gold_path.resolve())
        pred_obj = load_json(pred_path)
        gold_obj = load_json(gold_path)
        empty_match: bool | None = None
        if pred_obj == {} and gold_obj == {}:
            empty_match = True
            counts = Counts()
            notes.append("both empty {}")
        elif pred_obj == {} or gold_obj == {}:
            empty_match = False
            counts = score_leaves(pred_obj, gold_obj)
        else:
            counts = score_leaves(pred_obj, gold_obj)

        doc = DocScore(
            rel_path=rel,
            counts=counts,
            holdout=holdout,
            empty_match=empty_match,
            notes=notes,
        )
        report.docs.append(doc)
        report.total.merge(counts)
        (report.holdout if holdout else report.train).merge(counts)

    # Gold-only files (no matching pred) → FN leaves against empty pred.
    for gold_path in iter_json_files(gold_root):
        if gold_path.resolve() in matched_gold:
            continue
        rel = gold_path.relative_to(gold_root).as_posix()
        holdout = holdout_of(rel)
        notes = ["missing pred"]
        if holdout:
            notes.append("hold-out")
        gold_obj = load_json(gold_path)
        counts = score_leaves({}, gold_obj)
        empty_match: bool | None = False if gold_obj != {} else True
        if gold_obj == {}:
            counts = Counts()
            notes.append("both empty {}")
            empty_match = True
        doc = DocScore(
            rel_path=rel,
            counts=counts,
            holdout=holdout,
            empty_match=empty_match,
            notes=notes,
        )
        report.docs.append(doc)
        report.total.merge(counts)
        (report.holdout if holdout else report.train).merge(counts)

    return report


def format_report(report: EvalReport) -> str:
    lines = [
        (
            f"Micro-F1={report.total.f1:.4f}  P={report.total.precision:.4f}  "
            f"R={report.total.recall:.4f}  "
            f"TP={report.total.tp} FP={report.total.fp} FN={report.total.fn}"
        ),
        (
            f"Train  F1={report.train.f1:.4f} "
            f"(TP={report.train.tp} FP={report.train.fp} FN={report.train.fn})"
        ),
        (
            f"Hold-out (cases {report.holdout_min}-{report.holdout_max}) "
            f"F1={report.holdout.f1:.4f} "
            f"(TP={report.holdout.tp} FP={report.holdout.fp} FN={report.holdout.fn})"
        ),
        f"Documents scored: {len(report.docs)}",
    ]
    flagged = [d for d in report.docs if d.holdout]
    if flagged:
        lines.append(f"Hold-out docs: {len(flagged)}")
    return "\n".join(lines)


def format_report_markdown(report: EvalReport) -> str:
    """Markdown summary table suitable for submission attachment."""
    rows = [
        ("split", "F1", "precision", "recall", "TP", "FP", "FN"),
        (
            "all",
            f"{report.total.f1:.4f}",
            f"{report.total.precision:.4f}",
            f"{report.total.recall:.4f}",
            str(report.total.tp),
            str(report.total.fp),
            str(report.total.fn),
        ),
        (
            "train",
            f"{report.train.f1:.4f}",
            f"{report.train.precision:.4f}",
            f"{report.train.recall:.4f}",
            str(report.train.tp),
            str(report.train.fp),
            str(report.train.fn),
        ),
        (
            f"hold-out ({report.holdout_min}-{report.holdout_max})",
            f"{report.holdout.f1:.4f}",
            f"{report.holdout.precision:.4f}",
            f"{report.holdout.recall:.4f}",
            str(report.holdout.tp),
            str(report.holdout.fp),
            str(report.holdout.fn),
        ),
    ]
    lines = [
        "# TROP eval report",
        "",
        f"Documents scored: **{len(report.docs)}**",
        "",
        "| " + " | ".join(rows[0]) + " |",
        "| " + " | ".join("---" for _ in rows[0]) + " |",
    ]
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    lines.extend(["", "## Per document", ""])
    lines.append("| path | holdout | F1 | TP | FP | FN | notes |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for d in report.docs:
        notes = "; ".join(d.notes) if d.notes else ""
        lines.append(
            f"| {d.rel_path} | {d.holdout} | {d.counts.f1:.4f} | "
            f"{d.counts.tp} | {d.counts.fp} | {d.counts.fn} | {notes} |"
        )
    lines.append("")
    return "\n".join(lines)


def format_report_csv(report: EvalReport) -> str:
    """CSV table (summary rows + per-document rows)."""
    lines = [
        "kind,path,holdout,f1,precision,recall,tp,fp,fn,notes",
        (
            f"summary,all,,{report.total.f1:.4f},{report.total.precision:.4f},"
            f"{report.total.recall:.4f},{report.total.tp},{report.total.fp},"
            f"{report.total.fn},"
        ),
        (
            f"summary,train,,{report.train.f1:.4f},{report.train.precision:.4f},"
            f"{report.train.recall:.4f},{report.train.tp},{report.train.fp},"
            f"{report.train.fn},"
        ),
        (
            f"summary,holdout,,{report.holdout.f1:.4f},{report.holdout.precision:.4f},"
            f"{report.holdout.recall:.4f},{report.holdout.tp},{report.holdout.fp},"
            f"{report.holdout.fn},"
        ),
    ]
    for d in report.docs:
        notes = "; ".join(d.notes).replace(",", ";") if d.notes else ""
        lines.append(
            f"doc,{d.rel_path},{d.holdout},{d.counts.f1:.4f},"
            f"{d.counts.precision:.4f},{d.counts.recall:.4f},"
            f"{d.counts.tp},{d.counts.fp},{d.counts.fn},{notes}"
        )
    return "\n".join(lines) + "\n"


def write_report(report: EvalReport, path: Path) -> Path:
    """Write report as JSON, Markdown, or CSV based on ``path`` suffix."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".md":
        path.write_text(format_report_markdown(report), encoding="utf-8")
    elif suffix == ".csv":
        path.write_text(format_report_csv(report), encoding="utf-8")
    else:
        # Default / .json
        path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return path
