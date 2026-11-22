"""Load ClassSpec / negatives / dicts from YAML + JSON Schema on disk."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from trop.normalize.fns import NORMALIZERS
from trop.settings import _repo_root

logger = logging.getLogger(__name__)

EXTRACTOR_TYPES = frozenset({"regex", "regex_all", "label", "const", "derived"})


@dataclass(frozen=True)
class DetectKeyword:
    pattern: str
    weight: float = 1.0


@dataclass(frozen=True)
class DetectSpec:
    threshold: float = 5.0
    margin: float = 1.5
    keywords: tuple[DetectKeyword, ...] = ()


@dataclass(frozen=True)
class BlockSpec:
    id: str
    start: str | None = None
    end: str | None = None


@dataclass(frozen=True)
class ExtractorSpec:
    type: str
    pattern: str | None = None
    group: int = 1
    labels: tuple[str, ...] = ()
    value_pattern: str | None = None
    value_flags: str = ""
    stop_at: str | None = None
    normalize: tuple[str, ...] = ()
    block: str | None = None
    value: Any = None
    const_on_match: Any = None
    from_path: str | None = None
    via: str | None = None
    map_to_powod_id: bool = False
    wrap_key: str | None = None
    # label: max chars allowed between the label and its value (section headers
    # such as "Dane nadawcy" whose value sits a few lines below).
    window: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False)

    def label_regex(self, label: str) -> str:
        """Regex for a ``label`` extractor: label (case-insensitive) + value.

        The flag is scoped to the label so value patterns keep their case
        semantics (``[A-Z]`` means uppercase); ``value_flags: i`` relaxes them.
        The label must end on a word boundary ("Tytuł" ≠ "tytułu"); dot leaders
        ("KWOTA ....... 50,00") count as separator.
        """
        value_pat = self.value_pattern or r"([^\n]+)"
        gap = rf"[\s\S]{{0,{int(self.window)}}}?" if self.window else r"[\s:\-–.…·]*"
        return rf"(?i:{re.escape(label)})(?!\w){gap}{value_pat}"


@dataclass(frozen=True)
class FieldSpec:
    path: str
    extractors: tuple[ExtractorSpec, ...] = ()


@dataclass(frozen=True)
class ListFieldSpec:
    key: str
    extractors: tuple[ExtractorSpec, ...] = ()


@dataclass(frozen=True)
class ListSpec:
    path: str
    block: str | None = None
    mode: str = "single"
    item_pattern: str | None = None
    fields: tuple[ListFieldSpec, ...] = ()


@dataclass(frozen=True)
class ClassSpec:
    id: str
    label: str
    root: Path
    detect: DetectSpec
    blocks: tuple[BlockSpec, ...] = ()
    fields: tuple[FieldSpec, ...] = ()
    lists: tuple[ListSpec, ...] = ()
    schema: dict[str, Any] = field(default_factory=dict)
    dicts: dict[str, Any] = field(default_factory=dict)
    # Built once at load from a checked ``schema`` (None when there is none).
    validator: Draft202012Validator | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class NegativesConfig:
    anchors: tuple[DetectKeyword, ...] = ()
    veto_threshold: float = 5.0
    # Veto applies when best_class_score - negative_score < veto_margin.
    veto_margin: float = 2.0


def default_classes_dir() -> Path:
    return _repo_root() / "classes"


def default_negatives_path() -> Path:
    return _repo_root() / "config" / "negatives.yaml"


def _parse_extractor(raw: dict[str, Any]) -> ExtractorSpec:
    labels = raw.get("labels") or []
    if isinstance(labels, str):
        labels = [labels]
    norms = raw.get("normalize") or []
    if isinstance(norms, str):
        norms = [norms]
    return ExtractorSpec(
        type=str(raw.get("type", "regex")),
        pattern=raw.get("pattern"),
        group=int(raw.get("group", 1)),
        labels=tuple(str(x) for x in labels),
        value_pattern=raw.get("value_pattern"),
        value_flags=str(raw.get("value_flags") or ""),
        stop_at=raw.get("stop_at"),
        normalize=tuple(str(x) for x in norms),
        block=raw.get("block"),
        value=raw.get("value"),
        const_on_match=raw.get("const_on_match"),
        from_path=raw.get("from"),
        via=raw.get("via"),
        map_to_powod_id=bool(raw.get("map_to_powod_id", False)),
        wrap_key=raw.get("wrap_key"),
        window=int(raw["window"]) if raw.get("window") is not None else None,
        raw=dict(raw),
    )


def _parse_field(raw: dict[str, Any]) -> FieldSpec:
    extractors = tuple(_parse_extractor(e) for e in (raw.get("extractors") or []))
    return FieldSpec(path=str(raw["path"]), extractors=extractors)


def _parse_list(raw: dict[str, Any]) -> ListSpec:
    fields = tuple(
        ListFieldSpec(
            key=str(f["key"]),
            extractors=tuple(_parse_extractor(e) for e in (f.get("extractors") or [])),
        )
        for f in (raw.get("fields") or [])
    )
    return ListSpec(
        path=str(raw["path"]),
        block=raw.get("block"),
        mode=str(raw.get("mode") or "single"),
        item_pattern=raw.get("item_pattern"),
        fields=fields,
    )


def load_class_spec(class_dir: Path) -> ClassSpec:
    """Load one class directory containing ``class.yaml`` (+ optional schema/dicts)."""
    class_dir = Path(class_dir)
    yaml_path = class_dir / "class.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"Missing class.yaml in {class_dir}")

    with yaml_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid class.yaml: {yaml_path}")

    detect_raw = data.get("detect") or {}
    keywords = tuple(
        DetectKeyword(pattern=str(k["pattern"]), weight=float(k.get("weight", 1.0)))
        for k in (detect_raw.get("keywords") or [])
    )
    detect = DetectSpec(
        threshold=float(detect_raw.get("threshold", 5.0)),
        margin=float(detect_raw.get("margin", 1.5)),
        keywords=keywords,
    )
    blocks = tuple(
        BlockSpec(id=str(b["id"]), start=b.get("start"), end=b.get("end"))
        for b in (data.get("blocks") or [])
    )
    fields = tuple(_parse_field(f) for f in (data.get("fields") or []))
    lists = tuple(_parse_list(lst) for lst in (data.get("lists") or []))

    schema: dict[str, Any] = {}
    validator: Draft202012Validator | None = None
    schema_path = class_dir / "schema.json"
    if schema_path.is_file():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        # A broken schema fails the class load (reported once) instead of
        # turning every document of the class into {} at validation time.
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)

    dicts: dict[str, Any] = {}
    dicts_dir = class_dir / "dicts"
    if dicts_dir.is_dir():
        for path in sorted(dicts_dir.glob("*.yaml")):
            with path.open(encoding="utf-8") as fh:
                dicts[path.stem] = yaml.safe_load(fh) or {}

    return ClassSpec(
        id=str(data.get("id") or class_dir.name),
        label=str(data.get("label") or class_dir.name),
        root=class_dir,
        detect=detect,
        blocks=blocks,
        fields=fields,
        lists=lists,
        schema=schema,
        dicts=dicts,
        validator=validator,
    )


def _regex_problem(pattern: str | None, where: str) -> str | None:
    if not pattern:
        return None
    try:
        re.compile(pattern, re.MULTILINE)
    except re.error as exc:
        return f"{where}: invalid regex ({exc}): {pattern!r}"
    return None


def _extractor_problems(
    ex: ExtractorSpec,
    where: str,
    block_ids: set[str],
) -> list[str]:
    problems: list[str] = []
    if (ex.type or "regex").lower() not in EXTRACTOR_TYPES:
        problems.append(
            f"{where}: unknown extractor type {ex.type!r} "
            f"(expected one of {sorted(EXTRACTOR_TYPES)})"
        )
    checks = [(ex.pattern, f"{where}.pattern"), (ex.stop_at, f"{where}.stop_at")]
    if ex.type == "label":
        checks.append((ex.label_regex("label"), f"{where}.value_pattern"))
    problems += [p for pat, w in checks if (p := _regex_problem(pat, w))]
    problems += [
        f"{where}: unknown normalizer {name!r}" for name in ex.normalize if name not in NORMALIZERS
    ]
    if ex.block and ex.block not in block_ids:
        problems.append(f"{where}: unknown block {ex.block!r}")
    return problems


def validate_class_spec(spec: ClassSpec) -> list[str]:
    """Return config problems that would otherwise fail silently at runtime.

    Invalid regexes, unknown extractor types / normalizers and unknown block
    ids never raise during extraction — the field just stays ``None``.
    """
    src = f"{spec.root.name}/class.yaml"
    block_ids = {b.id for b in spec.blocks}
    problems: list[str] = []
    for i, kw in enumerate(spec.detect.keywords):
        if p := _regex_problem(kw.pattern, f"{src} detect.keywords[{i}]"):
            problems.append(p)
    for b in spec.blocks:
        for attr in ("start", "end"):
            if p := _regex_problem(getattr(b, attr), f"{src} blocks[{b.id}].{attr}"):
                problems.append(p)
    for fld in spec.fields:
        for i, ex in enumerate(fld.extractors):
            problems += _extractor_problems(
                ex, f"{src} fields[{fld.path}].extractors[{i}]", block_ids
            )
    for lst in spec.lists:
        if p := _regex_problem(lst.item_pattern, f"{src} lists[{lst.path}].item_pattern"):
            problems.append(p)
        if lst.block and lst.block not in block_ids:
            problems.append(f"{src} lists[{lst.path}]: unknown block {lst.block!r}")
        for lf in lst.fields:
            for i, ex in enumerate(lf.extractors):
                where = f"{src} lists[{lst.path}].fields[{lf.key}].extractors[{i}]"
                problems += _extractor_problems(ex, where, block_ids)
    return problems


def load_classes_report(
    classes_dir: Path | str | None = None,
) -> tuple[tuple[ClassSpec, ...], list[str]]:
    """Load class specs and collect every load / validation problem."""
    root = Path(classes_dir) if classes_dir else default_classes_dir()
    if not root.is_dir():
        return (), [f"Classes directory missing: {root}"]
    specs: list[ClassSpec] = []
    problems: list[str] = []
    for child in iter_class_dirs(root):
        try:
            spec = load_class_spec(child)
        except Exception as exc:  # noqa: BLE001 — isolate broken class folders
            problems.append(f"{child.name}/class.yaml: failed to load: {exc}")
            continue
        specs.append(spec)
        problems += validate_class_spec(spec)
    return tuple(sorted(specs, key=lambda s: s.id)), problems


def iter_class_dirs(classes_dir: Path | str | None = None) -> list[Path]:
    """Return class directories that contain ``class.yaml``.

    Skips folders whose names start with ``_`` (templates / scratch).
    """
    root = Path(classes_dir) if classes_dir else default_classes_dir()
    if not root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_"):
            logger.debug("Skipping template/scratch class dir: %s", child.name)
            continue
        if (child / "class.yaml").is_file():
            found.append(child)
    return found


@lru_cache
def load_classes(classes_dir: str | None = None) -> tuple[ClassSpec, ...]:
    """Load all class specs under ``classes/*/class.yaml`` (sorted by id).

    Folders starting with ``_`` (e.g. ``_template``) are ignored so templates
    never register. Adding a new ``classes/<id>/class.yaml`` is enough — no
    Python import required. Config problems are logged as errors; a class
    with a bad pattern still loads (that pattern just never matches), and
    ``trop classes list`` reports them with a non-zero exit.
    """
    specs, problems = load_classes_report(classes_dir)
    for problem in problems:
        logger.error("Class config problem: %s", problem)
    return specs


@lru_cache
def load_negatives(path: str | None = None) -> NegativesConfig:
    cfg_path = Path(path) if path else default_negatives_path()
    if not cfg_path.is_file():
        return NegativesConfig()
    with cfg_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    anchors = tuple(
        DetectKeyword(pattern=str(a["pattern"]), weight=float(a.get("weight", 1.0)))
        for a in (data.get("anchors") or [])
    )
    for i, anchor in enumerate(anchors):
        if problem := _regex_problem(anchor.pattern, f"{cfg_path.name} anchors[{i}]"):
            logger.error("Negatives config problem: %s", problem)
    return NegativesConfig(
        anchors=anchors,
        veto_threshold=float(data.get("veto_threshold", 5.0)),
        veto_margin=float(data.get("veto_margin", 2.0)),
    )


@lru_cache
def load_czynnosc_powod_dict(classes_dir: str | None = None) -> dict[int, str]:
    """Return ``{1: opis, ...}`` from odwolanie dict (keys coerced to int)."""
    root = Path(classes_dir) if classes_dir else default_classes_dir()
    path = root / "odwolanie" / "dicts" / "czynnosc_powod.yaml"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[int, str] = {}
    for key, value in raw.items():
        try:
            out[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return out


def clear_registry_cache() -> None:
    load_classes.cache_clear()
    load_negatives.cache_clear()
    load_czynnosc_powod_dict.cache_clear()
