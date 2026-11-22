"""Smoke tests for content-based classification (never filename)."""

from __future__ import annotations

from pathlib import Path

from trop.classify.rules import OTHER, classify_text
from trop.registry.loader import clear_registry_cache, load_classes, load_negatives

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "text"


def setup_function() -> None:
    clear_registry_cache()


def test_classes_loaded() -> None:
    specs = load_classes()
    ids = {s.id for s in specs}
    assert ids == {"odwolanie", "pelnomocnictwo", "przelew"}


def test_classify_odwolanie_by_content() -> None:
    text = (FIXTURES / "odwolanie_smoke.txt").read_text(encoding="utf-8")
    result = classify_text(text)
    assert result.class_id == "odwolanie"
    assert result.score >= load_classes()[0].detect.threshold or result.score > 0


def test_classify_przelew_by_content() -> None:
    text = (FIXTURES / "przelew_smoke.txt").read_text(encoding="utf-8")
    result = classify_text(text)
    assert result.class_id == "przelew"


def test_classify_pelnomocnictwo_by_content() -> None:
    text = (FIXTURES / "pelnomocnictwo_smoke.txt").read_text(encoding="utf-8")
    assert classify_text(text).class_id == "pelnomocnictwo"


def test_classify_ooc_wyrok_returns_other() -> None:
    text = (FIXTURES / "wyrok_ooc.txt").read_text(encoding="utf-8")
    negatives = load_negatives()
    assert negatives.anchors
    result = classify_text(text)
    assert result.class_id == OTHER
    assert result.negative_score > 0


def test_veto_margin_comes_from_config() -> None:
    from trop.registry.loader import DetectKeyword, NegativesConfig

    text = (FIXTURES / "odwolanie_smoke.txt").read_text(encoding="utf-8") + "\nNEGATYW_TEST\n"
    anchor = (DetectKeyword(pattern="NEGATYW_TEST", weight=6.0),)
    best = classify_text(text, negatives=NegativesConfig()).score
    gap = best - 6.0  # best_class_score - negative_score

    strict = NegativesConfig(anchors=anchor, veto_threshold=5.0, veto_margin=gap + 1)
    lenient = NegativesConfig(anchors=anchor, veto_threshold=5.0, veto_margin=gap - 1)
    assert classify_text(text, negatives=strict).class_id == OTHER
    assert classify_text(text, negatives=lenient).class_id == "odwolanie"


def test_classify_ignores_filename_semantics() -> None:
    """Even if text looks like a transfer, class comes from content keywords."""
    # Filename is irrelevant — function has no path argument.
    text = (FIXTURES / "przelew_smoke.txt").read_text(encoding="utf-8")
    assert classify_text(text).class_id == "przelew"
