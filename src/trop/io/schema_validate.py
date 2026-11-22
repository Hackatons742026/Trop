"""Validate scored payloads against per-class JSON Schema before write."""

from __future__ import annotations

import logging
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

logger = logging.getLogger(__name__)


def validate_payload(payload: Any, schema: dict[str, Any] | None) -> bool:
    """Return True if ``payload`` conforms to ``schema`` (or schema is empty)."""
    if not schema:
        return True
    try:
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)
        return True
    except (ValidationError, SchemaError) as exc:
        logger.error("JSON Schema validation failed: %s", exc)
        return False


def validated_or_empty(
    payload: Any,
    schema: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return ``payload`` when schema-valid; otherwise log and return ``{}``."""
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.error("Scored payload must be an object, got %s", type(payload).__name__)
        return {}
    if not payload:
        return {}
    if validate_payload(payload, schema):
        return payload
    return {}
