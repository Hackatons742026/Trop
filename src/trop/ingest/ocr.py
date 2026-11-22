"""RapidOCR wrapper (rapidocr + onnxruntime).

Models are downloaded on first use. For Docker, bake the model cache into the
image (see README / ops notes) so cold starts do not hit the network.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
from numpy.typing import NDArray

from trop.models import Line, Word

logger = logging.getLogger(__name__)

# Init + inference must share one lock: RapidOCR/onnxruntime is not thread-safe.
_engine_lock = threading.Lock()
_engine: Any | None = None


def _ensure_engine_locked() -> Any:
    """Create RapidOCR if needed. Caller must hold ``_engine_lock``."""
    global _engine
    if _engine is not None:
        return _engine
    from rapidocr import RapidOCR

    logger.info(
        "Initializing RapidOCR (onnxruntime); first run may download models"
    )
    _engine = RapidOCR()
    return _engine


def get_ocr_engine() -> Any:
    """Lazy-init a process-wide RapidOCR engine (thread-safe)."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        return _ensure_engine_locked()


def reset_ocr_engine() -> None:
    """Drop cached engine (tests)."""
    global _engine
    with _engine_lock:
        _engine = None


def ocr_image(image: NDArray[np.uint8]) -> tuple[str, list[Line]]:
    """Run OCR on an RGB or BGR numpy image; return full text + lines.

    Inference is serialized via ``_engine_lock`` so ``workers > 1`` remains safe
    when RapidOCR is used (see ``config/app.yaml`` ocr notes).
    """
    if image is None or image.size == 0:
        return "", []

    # Init + inference under one lock (RapidOCR/onnxruntime is not thread-safe).
    with _engine_lock:
        engine = _ensure_engine_locked()
        result = engine(image)

    # Avoid `x or ()` — RapidOCR may return numpy arrays (truth value ambiguous).
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    if txts is None:
        txts = ()
    if scores is None:
        scores = ()
    if boxes is None:
        boxes = ()

    lines: list[Line] = []
    parts: list[str] = []
    for i, text in enumerate(txts):
        if text is None:
            continue
        conf = float(scores[i]) if i < len(scores) and scores[i] is not None else None
        bbox = _box_to_bbox(boxes[i]) if i < len(boxes) else None
        word = Word(text=str(text), conf=conf, bbox=bbox)
        lines.append(Line(text=str(text), words=[word], conf=conf, bbox=bbox))
        parts.append(str(text))

    full = "\n".join(parts)
    return full, lines


def _box_to_bbox(box: Any) -> tuple[float, float, float, float] | None:
    """Convert a 4-point polygon to axis-aligned (x0, y0, x1, y1)."""
    try:
        pts = np.asarray(box, dtype=float)
        if pts.size < 4:
            return None
        xs = pts[:, 0] if pts.ndim == 2 else pts[0::2]
        ys = pts[:, 1] if pts.ndim == 2 else pts[1::2]
        return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())
    except Exception:  # noqa: BLE001 — best-effort geometry
        return None
