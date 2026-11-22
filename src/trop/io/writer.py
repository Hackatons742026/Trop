"""Write JSON outputs. Errors / OOC → exactly ``{}``."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

EMPTY_OBJECT: dict[str, Any] = {}


def write_json(path: Path, payload: Any) -> Path:
    """Serialize ``payload`` as UTF-8 JSON (ensure_ascii=False) to ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    # Trailing newline for POSIX friendliness.
    path.write_text(text + "\n", encoding="utf-8")
    return path


def write_empty_json(path: Path) -> Path:
    """Write exactly ``{}`` — used for P0 stub, OOC, and per-file errors."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exact empty object; no pretty-print extras beyond stable ``{}``.
    path.write_text("{}\n", encoding="utf-8")
    logger.debug("Wrote empty JSON: %s", path)
    return path


def read_json_object(path: Path) -> Any:
    """Load JSON from path (tests / debugging)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))
