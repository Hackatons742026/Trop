"""Primitive extractors: regex, label, regex_all, derived, const."""

from __future__ import annotations

import re
from typing import Any

from trop.extract.powod import map_text_to_powod_id, opis_for_id
from trop.normalize.fns import apply_normalizers
from trop.registry.loader import ExtractorSpec


def _compile(pattern: str, flags: str = "") -> re.Pattern[str]:
    f = re.MULTILINE
    if "i" in flags.lower() or "(?i)" in pattern:
        f |= re.IGNORECASE
    if "s" in flags.lower():
        f |= re.DOTALL
    return re.compile(pattern, f)


def _post(value: Any, spec: ExtractorSpec) -> Any:
    if value is None:
        return None
    if spec.const_on_match is not None:
        return spec.const_on_match
    if spec.map_to_powod_id:
        return map_text_to_powod_id(str(value))
    if spec.normalize:
        return apply_normalizers(value, spec.normalize)
    return value


def run_regex(text: str, spec: ExtractorSpec) -> Any:
    if not spec.pattern or not text:
        return None
    try:
        cre = _compile(spec.pattern)
    except re.error:
        return None
    m = cre.search(text)
    if not m:
        return None
    if spec.const_on_match is not None:
        return spec.const_on_match
    try:
        raw = m.group(spec.group)
    except IndexError:
        raw = m.group(0)
    return _post(raw, spec)


def run_regex_all(text: str, spec: ExtractorSpec) -> list[Any]:
    if not spec.pattern or not text:
        return []
    try:
        cre = _compile(spec.pattern)
    except re.error:
        return []
    out: list[Any] = []
    for m in cre.finditer(text):
        try:
            raw = m.group(spec.group)
        except IndexError:
            raw = m.group(0)
        val = _post(raw, spec)
        if val is None:
            continue
        if spec.wrap_key:
            out.append({spec.wrap_key: val})
        else:
            out.append(val)
    return out


def run_label(text: str, spec: ExtractorSpec) -> Any:
    if not text or not spec.labels:
        return None
    value_pat = spec.value_pattern or r"([^\n]+)"
    for label in spec.labels:
        # Label then optional :/- then capture
        pat = rf"(?i){re.escape(label)}\s*[:\-]?\s*{value_pat}"
        try:
            cre = _compile(pat, spec.value_flags)
        except re.error:
            continue
        m = cre.search(text)
        if not m:
            continue
        raw = m.group(1) if m.lastindex else m.group(0)
        if spec.stop_at:
            stop = re.search(spec.stop_at, raw)
            if stop:
                raw = raw[: stop.start()]
        return _post(raw, spec)
    return None


def run_const(spec: ExtractorSpec) -> Any:
    return spec.value


def run_derived(values: dict[str, Any], spec: ExtractorSpec) -> Any:
    if not spec.from_path:
        return None
    src = values.get(spec.from_path)
    if spec.via == "czynnosc_powod_opis":
        if isinstance(src, int):
            return opis_for_id(src)
        if isinstance(src, str) and src.isdigit():
            return opis_for_id(int(src))
        return None
    return src


def run_extractor(
    text: str,
    spec: ExtractorSpec,
    *,
    values: dict[str, Any] | None = None,
) -> Any:
    """Run a single extractor; return value or None (or list for regex_all)."""
    kind = (spec.type or "regex").lower()
    if kind == "regex":
        return run_regex(text, spec)
    if kind == "regex_all":
        return run_regex_all(text, spec)
    if kind == "label":
        return run_label(text, spec)
    if kind == "const":
        return run_const(spec)
    if kind == "derived":
        return run_derived(values or {}, spec)
    return None


def first_hit(
    text: str,
    specs: tuple[ExtractorSpec, ...],
    *,
    values: dict[str, Any] | None = None,
) -> Any:
    """Try extractors in order; return first non-None (empty list skipped)."""
    for spec in specs:
        val = run_extractor(text, spec, values=values)
        if val is None:
            continue
        if isinstance(val, list) and not val:
            continue
        return val
    return None
