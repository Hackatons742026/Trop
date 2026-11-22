"""Text block slicing for scoped extractors."""

from __future__ import annotations

import re

from trop.registry.loader import BlockSpec


def document_text(pages_text: list[str]) -> str:
    return "\n".join(t for t in pages_text if t)


def slice_blocks(text: str, blocks: tuple[BlockSpec, ...]) -> dict[str, str]:
    """Return ``{block_id: substring}`` using start/end regex anchors."""
    out: dict[str, str] = {}
    if not text:
        return out
    for block in blocks:
        start_idx = 0
        if block.start:
            m = re.search(block.start, text, flags=re.MULTILINE)
            if m:
                start_idx = m.start()
            else:
                out[block.id] = ""
                continue
        end_idx = len(text)
        if block.end:
            m = re.search(block.end, text[start_idx + 1 :], flags=re.MULTILINE)
            if m:
                end_idx = start_idx + 1 + m.start()
        out[block.id] = text[start_idx:end_idx]
    return out


def resolve_scope(
    full_text: str,
    blocks: dict[str, str],
    block_id: str | None,
) -> str:
    if block_id and block_id in blocks and blocks[block_id]:
        return blocks[block_id]
    return full_text
