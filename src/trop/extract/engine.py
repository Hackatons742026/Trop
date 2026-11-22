"""Orchestrate block slicing + field/list extraction → schema-shaped dict."""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from trop.extract.blocks import document_text, resolve_scope, slice_blocks
from trop.extract.extractors import first_hit
from trop.models import Document, FieldValue, TextSource
from trop.registry.loader import ClassSpec, ListSpec

logger = logging.getLogger(__name__)


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    """Set dotted path on nested dicts (creates intermediate dicts)."""
    parts = path.split(".")
    cur: Any = root
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if last:
            if isinstance(cur, dict):
                cur[part] = value
            return
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]


def _set_nested_item(item: dict[str, Any], key: str, value: Any) -> None:
    """Set ``a.b.c`` inside a list item dict."""
    if "." not in key:
        item[key] = value
        return
    _set_path(item, key, value)


def _skeleton_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Build a null-filled skeleton from JSON Schema properties (best-effort)."""
    if not schema:
        return {}
    return _skeleton_props(schema)


def _skeleton_props(node: dict[str, Any]) -> Any:
    t = node.get("type")
    types = t if isinstance(t, list) else [t]
    if "object" in types or "properties" in node:
        props = node.get("properties") or {}
        return {k: _skeleton_props(v) for k, v in props.items()}
    if "array" in types:
        return []
    if "null" in types and len(types) > 1:
        return None
    if "integer" in types or "number" in types:
        return None
    if "string" in types:
        return None
    return None


def _extract_list_item(
    chunk: str,
    text: str,
    blocks: dict[str, str],
    fields: tuple,
    *,
    label: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {}
    for field in fields:
        # Extractor-level ``block:`` scopes this field (e.g. signatures).
        block_id = next((e.block for e in field.extractors if e.block), None)
        if block_id:
            field_scope = resolve_scope(text, blocks, block_id)
            # Consortium: keep only the "W imieniu <label>:" slice of the
            # signature block so each mocodawca gets its own signatories.
            if label and field.key == "podpisujacy":
                sliced = _slice_imieniu(field_scope, label)
                if sliced:
                    field_scope = sliced
        else:
            field_scope = chunk
        val = first_hit(field_scope, field.extractors)
        # Chunk miss → try a label-scoped window in the full document (KRS/NIP
        # for a consortium member live in the preamble, not the signature slice).
        if val is None and label and field.key.startswith("data."):
            window = _window_around_label(text, label, radius=180)
            if window:
                val = first_hit(window, field.extractors)
        # Never fall back to the full document for list items: identity fields
        # from another party leak (e.g. Zamawiający picking Odwołujący's KRS).
        _set_nested_item(item, field.key, val)
    return item


def _is_duplicate_person(items: list[dict[str, Any]], item: dict[str, Any]) -> bool:
    """True when ``item`` repeats an ``imie_nazwisko`` already in ``items``."""
    name = item.get("imie_nazwisko")
    if not isinstance(name, str) or not name:
        return False
    key = name.casefold()
    for prev in items:
        prev_name = prev.get("imie_nazwisko")
        if isinstance(prev_name, str) and prev_name.casefold() == key:
            return True
    return False


def _norm_firm_label(label: str) -> str:
    """Strip trailing punctuation but keep internal dots (``sp. z o.o.``)."""
    return label.strip().strip(":;").strip()


def _slice_imieniu(text: str, label: str) -> str | None:
    """Return the signature paragraph for ``W imieniu <label>:`` … next heading."""
    if not text or not label:
        return None
    firm = _norm_firm_label(label)
    escaped = re.escape(firm)
    # Trailing ``.?``: gold labels may omit the final dot of ``sp. z o.o.``.
    try:
        cre = re.compile(
            rf"(?i)W\s+imieniu\s+{escaped}\.?\s*:(.*?)(?=(?:W\s+imieniu\s+)|(?:Pełnomocnictwo\s+przyjmuję)|$)",
            flags=re.DOTALL,
        )
    except re.error:
        return None
    m = cre.search(text)
    return m.group(0) if m else None


def _window_around_label(text: str, label: str, *, radius: int) -> str | None:
    if not text or not label:
        return None
    firm = _norm_firm_label(label)
    parts = [p for p in re.split(r"\s+", firm) if p]
    if not parts:
        return None
    # Consortium preambles wrap mid-name ("Torvex\nBudownictwo sp. z o.o., … KRS").
    pat = r"\s+".join(re.escape(p) for p in parts)
    try:
        m = re.search(pat, text, flags=re.IGNORECASE)
    except re.error:
        m = None
    if m is None and firm.endswith("."):
        try:
            parts[-1] = parts[-1].rstrip(".")
            pat = r"\s+".join(re.escape(p) for p in parts if p)
            m = re.search(pat, text, flags=re.IGNORECASE)
        except re.error:
            m = None
    if m is None:
        return None
    return text[m.start() : min(len(text), m.end() + radius)]


def _extract_list(text: str, blocks: dict[str, str], lst: ListSpec) -> list[dict[str, Any]]:
    scope = resolve_scope(text, blocks, lst.block)
    mode = (lst.mode or "single").lower()

    if mode == "multi_from_regex" and lst.item_pattern:
        try:
            matches = list(re.finditer(lst.item_pattern, scope, flags=re.MULTILINE))
        except re.error:
            matches = []
        items: list[dict[str, Any]] = []
        for idx, match in enumerate(matches):
            # Scope for each item: from this match to next (or +200 chars).
            start = match.start()
            if idx + 1 < len(matches):
                end = matches[idx + 1].start()
            else:
                end = min(len(scope), match.end() + 240)
            chunk = scope[start:end]
            label = next((g for g in match.groups() if g), None)
            item = _extract_list_item(chunk, text, blocks, lst.fields, label=label)
            # Only seed data.nazwa when this list actually declares that field
            # (mocodawca). Attorney lists must not grow a nested ``data`` object.
            has_nazwa_field = any(f.key == "data.nazwa" for f in lst.fields)
            if (
                label
                and has_nazwa_field
                and not (isinstance(item.get("data"), dict) and item["data"].get("nazwa"))
            ):
                from trop.normalize.fns import collapse_ws

                _set_nested_item(item, "data.nazwa", collapse_ws(label.strip().rstrip(".,;")))
            # Avoid empty-only items and duplicate person names in one list.
            if not any(v is not None and v != [] for v in _leaf_values(item)):
                continue
            if _is_duplicate_person(items, item):
                continue
            items.append(item)
        if items:
            return _finalize_list_items(lst.path, items)
        # No item matches → one item from the whole list scope (single mocodawca).

    # Default: single item from block/scope
    item = _extract_list_item(scope, text, blocks, lst.fields)
    if any(v is not None and v != [] for v in _leaf_values(item)):
        return _finalize_list_items(lst.path, [item])
    return []


def _finalize_list_items(path: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Domain post-pass for multi-party lists (joint contracting authorities)."""
    if path == "Zamawiajacy" and len(items) > 1:
        if any(it.get("prowadzacy_postepowanie") == 1 for it in items):
            for it in items:
                if it.get("prowadzacy_postepowanie") is None:
                    it["prowadzacy_postepowanie"] = 0
    if path == "mocodawca":
        for it in items:
            data = it.get("data")
            if not isinstance(data, dict):
                continue
            signers = it.get("podpisujacy") if isinstance(it.get("podpisujacy"), list) else []
            # Sole-trader scans often only expose the name via the e-sign line.
            if (
                not data.get("imie_nazwisko")
                and data.get("nip")
                and not data.get("krs")
                and len(signers) == 1
                and isinstance(signers[0], dict)
                and signers[0].get("imie_nazwisko")
            ):
                data["imie_nazwisko"] = signers[0]["imie_nazwisko"]
            if (
                data.get("typ") is None
                and data.get("imie_nazwisko")
                and data.get("nip")
                and not data.get("krs")
            ):
                data["typ"] = "osoba_fizyczna"
    return items


def _leaf_values(obj: Any) -> list[Any]:
    if isinstance(obj, dict):
        out: list[Any] = []
        for v in obj.values():
            out.extend(_leaf_values(v))
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            out.extend(_leaf_values(v))
        return out
    return [obj]


def _list_item_skeleton(schema: dict[str, Any], path: str) -> dict[str, Any]:
    """Null-filled skeleton for one item of the top-level array ``path``."""
    node = (schema.get("properties") or {}).get(path) or {}
    items = node.get("items")
    skeleton = _skeleton_props(items) if isinstance(items, dict) else None
    return skeleton if isinstance(skeleton, dict) else {}


def _fill_defaults(target: dict[str, Any], skeleton: dict[str, Any]) -> None:
    """Add keys missing from ``target`` (recursively) using the schema skeleton.

    ``None`` where the schema expects an object / array becomes ``{…}`` / ``[]``.
    """
    for key, default in skeleton.items():
        current = target.get(key)
        if key not in target or (current is None and isinstance(default, (dict, list))):
            target[key] = copy.deepcopy(default)
        elif isinstance(default, dict) and isinstance(current, dict):
            _fill_defaults(current, default)


def extract_payload(text: str, spec: ClassSpec) -> dict[str, Any]:
    """Extract a schema-shaped payload from plain text for one class."""
    blocks = slice_blocks(text, spec.blocks)
    payload: dict[str, Any] = _skeleton_from_schema(spec.schema) if spec.schema else {}
    flat_values: dict[str, Any] = {}

    # Scalar fields — each extractor may declare its own block; missing → full text.
    for field in spec.fields:
        val = None
        used_block = False
        for extractor in field.extractors:
            scope = (
                resolve_scope(text, blocks, extractor.block)
                if extractor.block
                else text
            )
            if extractor.block:
                used_block = True
            val = first_hit(scope, (extractor,), values=flat_values)
            if val is not None:
                break
        # Block-scoped misses fall back to the same extractors on the full text.
        if val is None and used_block:
            val = first_hit(text, field.extractors, values=flat_values)
        flat_values[field.path] = val
        _set_path(payload, field.path, val)

    # Second pass for derived that depended on earlier paths
    for field in spec.fields:
        if not field.extractors:
            continue
        if field.extractors[0].type != "derived":
            continue
        val = first_hit(text, field.extractors, values=flat_values)
        flat_values[field.path] = val
        _set_path(payload, field.path, val)

    # Lists: missing item keys come from the class schema, not from code.
    for lst in spec.lists:
        items = _extract_list(text, blocks, lst)
        skeleton = _list_item_skeleton(spec.schema, lst.path)
        for item in items:
            _fill_defaults(item, skeleton)
        payload[lst.path] = items

    return payload


def extract_document(document: Document, spec: ClassSpec) -> dict[str, Any]:
    """Extract payload from an ingested Document; also fill FieldValue stubs."""
    text = document_text([p.text for p in document.pages])
    payload = extract_payload(text, spec)
    # FieldValue stubs used by evidence sidecars (scored JSON stays clean).
    document_fields: list[FieldValue] = []
    for path, value in _flatten(payload):
        document_fields.append(
            FieldValue(
                name=path,
                value=value,
                conf=None,
                source=TextSource.MIXED if document.pages else TextSource.EMPTY,
            )
        )
    document.fields = document_fields
    return payload


def _flatten(obj: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            path = f"{prefix}[{i}]"
            out.extend(_flatten(v, path))
    else:
        out.append((prefix, obj))
    return out

