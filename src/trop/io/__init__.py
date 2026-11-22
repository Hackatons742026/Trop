"""I/O helpers: discovery, JSON writers, and evidence sidecars."""

from trop.io.discover import discover_pdfs, output_json_path
from trop.io.evidence import evidence_json_path, write_evidence_sidecar
from trop.io.writer import write_empty_json, write_json

__all__ = [
    "discover_pdfs",
    "evidence_json_path",
    "output_json_path",
    "write_empty_json",
    "write_evidence_sidecar",
    "write_json",
]
