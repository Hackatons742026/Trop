"""Weighted keyword classifier with threshold / margin and global negatives."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from trop.models import Document
from trop.registry.loader import ClassSpec, NegativesConfig, load_classes, load_negatives

OTHER = "other"


@dataclass
class ClassificationResult:
    class_id: str
    score: float
    margin: float
    scores: dict[str, float] = field(default_factory=dict)
    negative_score: float = 0.0
    hits: dict[str, list[str]] = field(default_factory=dict)


def _score_keywords(text: str, patterns: tuple) -> tuple[float, list[str]]:
    total = 0.0
    hits: list[str] = []
    for kw in patterns:
        try:
            if re.search(kw.pattern, text, flags=re.MULTILINE):
                total += float(kw.weight)
                hits.append(kw.pattern)
        except re.error:
            continue
    return total, hits


def classify_text(
    text: str,
    *,
    classes: tuple[ClassSpec, ...] | None = None,
    negatives: NegativesConfig | None = None,
) -> ClassificationResult:
    """Classify by CONTENT only. Returns ``other`` when uncertain / OOC."""
    specs = classes if classes is not None else load_classes()
    neg = negatives if negatives is not None else load_negatives()
    body = text or ""

    scores: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for spec in specs:
        score, hit_list = _score_keywords(body, spec.detect.keywords)
        scores[spec.id] = score
        hits[spec.id] = hit_list

    neg_score, neg_hits = _score_keywords(body, neg.anchors)
    hits["_negatives"] = neg_hits

    if not scores:
        return ClassificationResult(
            class_id=OTHER,
            score=0.0,
            margin=0.0,
            scores=scores,
            negative_score=neg_score,
            hits=hits,
        )

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_id, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best_score - second_score

    # Hard veto: strong negatives without decisive positive class evidence.
    if neg_score >= neg.veto_threshold and best_score - neg_score < neg.veto_margin:
        return ClassificationResult(
            class_id=OTHER,
            score=best_score,
            margin=margin,
            scores=scores,
            negative_score=neg_score,
            hits=hits,
        )

    best_spec = next(s for s in specs if s.id == best_id)
    if best_score < best_spec.detect.threshold or margin < best_spec.detect.margin:
        return ClassificationResult(
            class_id=OTHER,
            score=best_score,
            margin=margin,
            scores=scores,
            negative_score=neg_score,
            hits=hits,
        )

    return ClassificationResult(
        class_id=best_id,
        score=best_score,
        margin=margin,
        scores=scores,
        negative_score=neg_score,
        hits=hits,
    )


def classify_document(
    document: Document,
    *,
    classes: tuple[ClassSpec, ...] | None = None,
    negatives: NegativesConfig | None = None,
) -> ClassificationResult:
    """Classify a Document using concatenated page text (content only)."""
    text = "\n".join(p.text for p in document.pages if p.text)
    result = classify_text(text, classes=classes, negatives=negatives)
    document.doc_class = result.class_id
    return result
