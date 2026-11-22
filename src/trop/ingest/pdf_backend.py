"""PDF backend protocol and pypdfium2 implementation (default, AGPL-safe).

No PyMuPDF on the default path.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import numpy as np
import pypdfium2 as pdfium
from numpy.typing import NDArray

# PDFium is not thread-safe: no two PDFium calls may run at the same time, not
# even on different documents (ctypes releases the GIL, so they really do
# overlap). Every pypdfium2 call goes through this lock so the threaded
# orchestrator and concurrent Streamlit sessions cannot crash the process.
_PDFIUM_LOCK = threading.RLock()


@dataclass(frozen=True)
class RenderedPage:
    """Rasterized page as RGB uint8 array (H, W, 3)."""

    index: int
    image: NDArray[np.uint8]
    width_pt: float
    height_pt: float


@runtime_checkable
class PdfBackend(Protocol):
    """Minimal PDF access surface used by ingest."""

    def page_count(self) -> int: ...

    def page_size(self, index: int) -> tuple[float, float]: ...

    def extract_text(self, index: int) -> str: ...

    def render_page(self, index: int, dpi: int) -> RenderedPage: ...

    def close(self) -> None: ...


class PdfiumBackend:
    """Default backend backed by pypdfium2 / PDFium.

    All PDFium access is serialized through ``_PDFIUM_LOCK``.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        with _PDFIUM_LOCK:
            self._doc = pdfium.PdfDocument(str(self._path))

    def page_count(self) -> int:
        with _PDFIUM_LOCK:
            return len(self._doc)

    def page_size(self, index: int) -> tuple[float, float]:
        with _PDFIUM_LOCK:
            page = self._doc[index]
            try:
                width, height = page.get_size()
                return float(width), float(height)
            finally:
                page.close()

    def extract_text(self, index: int) -> str:
        with _PDFIUM_LOCK:
            page = self._doc[index]
            try:
                textpage = page.get_textpage()
                try:
                    return textpage.get_text_bounded() or ""
                finally:
                    textpage.close()
            finally:
                page.close()

    def render_page(self, index: int, dpi: int) -> RenderedPage:
        with _PDFIUM_LOCK:
            page = self._doc[index]
            try:
                width_pt, height_pt = page.get_size()
                scale = dpi / 72.0
                bitmap = page.render(scale=scale)
                try:
                    # to_numpy is a view of the bitmap buffer (BGR/BGRx); copy it
                    # into a standalone RGB array before the bitmap is closed.
                    rgb = _to_rgb(bitmap.to_numpy())
                finally:
                    bitmap.close()
            finally:
                page.close()
        return RenderedPage(
            index=index,
            image=rgb,
            width_pt=float(width_pt),
            height_pt=float(height_pt),
        )

    def close(self) -> None:
        with _PDFIUM_LOCK:
            self._doc.close()

    def __enter__(self) -> PdfiumBackend:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _to_rgb(arr: NDArray[np.uint8]) -> NDArray[np.uint8]:
    """Normalize pdfium bitmap arrays to contiguous RGB uint8."""
    if arr.ndim == 2:
        return np.stack([arr, arr, arr], axis=-1)
    if arr.ndim != 3:
        raise ValueError(f"Unexpected bitmap shape: {arr.shape}")
    channels = arr.shape[2]
    if channels == 3:
        # Pdfium default is BGR — convert to RGB.
        return arr[:, :, ::-1].copy()
    if channels == 4:
        # BGRA / BGRx → RGB
        return arr[:, :, 2::-1].copy()
    raise ValueError(f"Unsupported channel count: {channels}")


def open_backend(path: Path | str) -> PdfiumBackend:
    """Open a PDF with the default pypdfium2 backend."""
    return PdfiumBackend(path)
