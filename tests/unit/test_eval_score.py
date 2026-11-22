"""F1 harness: TN ignored, fuzzy long-strings, hold-out flags."""

from __future__ import annotations

import json
from pathlib import Path

from eval.score import (
    evaluate,
    format_report_csv,
    format_report_markdown,
    is_absent,
    is_holdout_path,
    score_leaves,
    values_equal,
    write_report,
)


def test_tn_both_null_not_counted() -> None:
    c = score_leaves(None, None)
    assert c.tp == c.fp == c.fn == 0
    c2 = score_leaves({"a": None}, {"a": None})
    assert c2.tp == c2.fp == c2.fn == 0


def test_exact_and_fuzzy() -> None:
    assert values_equal("abc", "abc", "krs")
    assert not values_equal("abc", "abd", "krs")
    assert values_equal(
        "Kancelaria Adwokacka i Partnerzy",
        "Kancelaria Adwokacka i Partnerzy Sp.",
        "Odwolujacy[0].pelnomocnik.nazwa",
    )


def test_fuzzy_rejects_token_subsets() -> None:
    """token_set_ratio scored these 100; they are partial / over-captures."""
    assert not values_equal("Gmina", "Gmina Miejska Kraków", "Zamawiajacy[0].nazwa")
    assert not values_equal("sp. z o.o.", "Budex sp. z o.o.", "Odwolujacy[0].nazwa")
    assert not values_equal(
        "Budex sp. z o.o. z siedzibą w Krakowie, KRS 0000123456, NIP 6762345678",
        "Budex sp. z o.o.",
        "mocodawca[0].data.nazwa",
    )


def test_holdout_cases() -> None:
    assert is_holdout_path("przyklad_46/odwolanie.json")
    assert is_holdout_path("przyklad_60/x.json")
    assert not is_holdout_path("przyklad_45/odwolanie.json")
    assert not is_holdout_path("negatywne/wyrok.json")


def test_is_absent() -> None:
    assert is_absent(None)
    assert is_absent("")
    assert not is_absent(0)
    assert not is_absent("x")


def test_evaluate_empty_pair(tmp_path: Path) -> None:
    pred = tmp_path / "pred" / "przyklad_10"
    gold = tmp_path / "gold" / "przyklad_10"
    pred.mkdir(parents=True)
    gold.mkdir(parents=True)
    (pred / "ooc.json").write_text("{}\n", encoding="utf-8")
    (gold / "ooc.json").write_text("{}\n", encoding="utf-8")
    # hold-out sample with mismatch
    pred46 = tmp_path / "pred" / "przyklad_46"
    gold46 = tmp_path / "gold" / "przyklad_46"
    pred46.mkdir()
    gold46.mkdir()
    (pred46 / "a.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
    (gold46 / "a.json").write_text(json.dumps({"x": 1}), encoding="utf-8")

    report = evaluate(tmp_path / "pred", tmp_path / "gold")
    assert any(d.empty_match for d in report.docs)
    assert any(d.holdout for d in report.docs)
    assert report.holdout.tp >= 1


def test_evaluate_gold_only_counts_as_fn(tmp_path: Path) -> None:
    """Gold file with no matching pred → FN leaves (not skipped)."""
    pred = tmp_path / "pred"
    gold = tmp_path / "gold"
    pred.mkdir()
    gold.mkdir()
    (gold / "only_gold.json").write_text(
        json.dumps({"k": "expected"}),
        encoding="utf-8",
    )
    report = evaluate(pred, gold)
    assert len(report.docs) == 1
    assert "missing pred" in report.docs[0].notes
    assert report.total.fn >= 1
    assert report.total.tp == 0


def test_write_report_md_and_csv(tmp_path: Path) -> None:
    pred = tmp_path / "pred"
    gold = tmp_path / "gold"
    pred.mkdir()
    gold.mkdir()
    (pred / "a.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")
    (gold / "a.json").write_text(json.dumps({"k": "v"}), encoding="utf-8")
    report = evaluate(pred, gold)

    md_path = tmp_path / "reports" / "f1.md"
    csv_path = tmp_path / "reports" / "f1.csv"
    json_path = tmp_path / "reports" / "f1.json"
    write_report(report, md_path)
    write_report(report, csv_path)
    write_report(report, json_path)

    md = md_path.read_text(encoding="utf-8")
    assert "| split |" in md
    assert "# TROP eval report" in md
    assert format_report_markdown(report).startswith("# TROP eval report")

    csv = csv_path.read_text(encoding="utf-8")
    assert "kind,path,holdout,f1" in csv
    assert "summary,all," in csv
    assert format_report_csv(report).startswith("kind,")

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "micro_f1" in data
