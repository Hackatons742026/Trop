"""Align predicted / gold JSON arrays by content (greedy name match)."""

from __future__ import annotations

from typing import Any

from rapidfuzz import fuzz

# Keys preferred when aligning list-of-objects (order-insensitive).
_NAME_KEYS = (
    "nazwa",
    "imie_nazwisko",
    "tytul",
    "numer_postepowania",
    "numer_transakcji",
    "krs",
    "nip",
)


def _name_fingerprint(item: Any) -> str:
    if not isinstance(item, dict):
        return str(item) if item is not None else ""
    parts: list[str] = []
    # Nested data.nazwa (mocodawca)
    data = item.get("data")
    if isinstance(data, dict):
        for key in _NAME_KEYS:
            val = data.get(key)
            if val:
                parts.append(str(val))
    for key in _NAME_KEYS:
        val = item.get(key)
        if val:
            parts.append(str(val))
    if not parts:
        # Fallback: stable dump of scalar leaves
        for k, v in sorted(item.items()):
            if isinstance(v, (str, int, float)) and v is not None:
                parts.append(f"{k}={v}")
    return " | ".join(parts).casefold()


def greedy_align(
    pred_list: list[Any],
    gold_list: list[Any],
    *,
    score_cutoff: float = 50.0,
) -> list[tuple[Any | None, Any | None]]:
    """Greedy bipartite match by fuzzy name fingerprint; unpaired → (x, None)/(None, y)."""
    if not isinstance(pred_list, list):
        pred_list = []
    if not isinstance(gold_list, list):
        gold_list = []

    pairs: list[tuple[Any | None, Any | None]] = []
    used_gold: set[int] = set()

    # Score matrix greedily from best pred→gold
    candidates: list[tuple[float, int, int]] = []
    for i, p in enumerate(pred_list):
        pf = _name_fingerprint(p)
        for j, g in enumerate(gold_list):
            gf = _name_fingerprint(g)
            if not pf and not gf:
                score = 100.0
            elif not pf or not gf:
                score = 0.0
            else:
                score = float(fuzz.token_set_ratio(pf, gf))
            candidates.append((score, i, j))
    candidates.sort(reverse=True)

    matched_pred: set[int] = set()
    for score, i, j in candidates:
        if i in matched_pred or j in used_gold:
            continue
        pf = _name_fingerprint(pred_list[i])
        gf = _name_fingerprint(gold_list[j])
        if score < score_cutoff and pf and gf:
            # Low scores only when both empty-ish; otherwise leave for leftovers.
            continue
        pairs.append((pred_list[i], gold_list[j]))
        matched_pred.add(i)
        used_gold.add(j)

    for i, p in enumerate(pred_list):
        if i not in matched_pred:
            pairs.append((p, None))
    for j, g in enumerate(gold_list):
        if j not in used_gold:
            pairs.append((None, g))
    return pairs


def align_lists(pred: Any, gold: Any) -> list[tuple[Any | None, Any | None]]:
    """Public helper used by the F1 scorer."""
    p = pred if isinstance(pred, list) else []
    g = gold if isinstance(gold, list) else []
    return greedy_align(p, g)
