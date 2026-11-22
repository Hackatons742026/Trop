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
            item: dict[str, Any] = {}
            for field in lst.fields:
                val = first_hit(chunk, field.extractors)
                _set_nested_item(item, field.key, val)
            # Avoid empty-only items
            if any(v is not None and v != [] for v in _leaf_values(item)):
                items.append(item)
        return items

    # Default: single item from block/scope
    item = {}
    for field in lst.fields:
        # An extractor-level ``block:`` scopes this field instead of the list
        # block (e.g. signatures live after the mocodawca section).
        block_id = next((e.block for e in field.extractors if e.block), None)
        field_scope = resolve_scope(text, blocks, block_id) if block_id else scope
        # regex_all results are lists; first_hit skips empty ones, and an
        # unmatched array field becomes [] from the schema skeleton later.
        val = first_hit(field_scope, field.extractors)
        _set_nested_item(item, field.key, val)

    # typ / osoba_prawna cleanup for mocodawca
    if "data" in item and isinstance(item["data"], dict):
        data = item["data"]
        if data.get("krs") or data.get("nip"):
            data["typ"] = "osoba_prawna"
            if data.get("imie_nazwisko") is None:
                data.setdefault("imie_nazwisko", None)
        elif data.get("imie_nazwisko"):
            data["typ"] = "osoba_fizyczna"

    if any(v is not None and v != [] for v in _leaf_values(item)):
        return [item]
    return []


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

    # Scalar fields
    for field in spec.fields:
        scope = text
        # Prefer block from first extractor that declares one
        block_id = next((e.block for e in field.extractors if e.block), None)
        if block_id:
            scope = resolve_scope(text, blocks, block_id)
        # derived uses flat_values
        if field.extractors and field.extractors[0].type == "derived":
            val = first_hit(scope, field.extractors, values=flat_values)
        else:
            # For fields with a dedicated block on extractors, try block then full text
            val = first_hit(scope, field.extractors, values=flat_values)
            if val is None and scope is not text:
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
    document.__dict__["_extracted_fields"] = document_fields
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


def empty_payload() -> dict[str, Any]:
    return copy.deepcopy({})
