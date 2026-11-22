"""Smoke tests for extract → schema payload."""

from __future__ import annotations

import json
from pathlib import Path

from eval.score import score_leaves
from trop.extract.engine import extract_payload
from trop.extract.powod import map_text_to_powod_id
from trop.io.schema_validate import validate_payload
from trop.registry.loader import clear_registry_cache, load_classes

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TEXT = FIXTURES / "text"
GOLD = FIXTURES / "gold"


def setup_function() -> None:
    clear_registry_cache()


def _spec(class_id: str):
    return next(s for s in load_classes() if s.id == class_id)


def test_extract_odwolanie_smoke() -> None:
    text = (TEXT / "odwolanie_smoke.txt").read_text(encoding="utf-8")
    payload = extract_payload(text, _spec("odwolanie"))
    assert "OdwolanieKIO" in payload
    assert payload["OdwolanieKIO"]["czynnosc_powod_id"] == 1
    assert payload["OdwolanieKIO"]["czynnosc_opis"] == "Decyzja o odrzuceniu oferty"
    assert payload["OdwolanieKIO"]["data"] == "2026-09-03"
    assert payload["ZamowieniePubliczne"]["numer_postepowania"] == "ZP.431.2026"
    assert payload["ZamowieniePubliczne"]["numer_ted"] == "999073-2026"
    assert payload["Odwolujacy"]
    assert payload["Odwolujacy"][0]["krs"] == "9999669444"
    assert payload["Odwolujacy"][0]["przez-pelnomocnika"] == 1
    assert validate_payload(payload, _spec("odwolanie").schema)


def test_extract_przelew_smoke() -> None:
    text = (TEXT / "przelew_smoke.txt").read_text(encoding="utf-8")
    payload = extract_payload(text, _spec("przelew"))
    bank = payload["przelew_bankowy"]
    assert bank["data_operacji"] == "2026-08-23"
    assert bank["kwota"] == 50.0
    assert bank["numer_transakcji"] == "CEN2609035760798"
    assert bank["tytul"] and "opłata" in bank["tytul"].lower()
    assert bank["z_rachunku"]
    assert bank["na_rachunek"]
    assert validate_payload(payload, _spec("przelew").schema)


def test_null_filled_skeleton_is_schema_valid() -> None:
    """Empty extract still yields schema-valid null-filled object (not invalid types)."""
    for class_id in ("odwolanie", "przelew", "pelnomocnictwo"):
        spec = _spec(class_id)
        payload = extract_payload("brak treści klasowej xyz", spec)
        assert isinstance(payload, dict)
        assert validate_payload(payload, spec.schema)


def test_micro_f1_against_odwolanie_gold() -> None:
    """Extract fixture text and score micro-F1 vs gold JSON."""
    text = (TEXT / "odwolanie_smoke.txt").read_text(encoding="utf-8")
    gold = json.loads((GOLD / "odwolanie_smoke.json").read_text(encoding="utf-8"))
    payload = extract_payload(text, _spec("odwolanie"))
    assert validate_payload(payload, _spec("odwolanie").schema)
    counts = score_leaves(payload, gold)
    assert counts.tp >= 10
    assert counts.f1 >= 0.7


def test_bare_swz_does_not_map_to_powod_4() -> None:
    assert map_text_to_powod_id("dotyczy SWZ") is None
    assert map_text_to_powod_id("specyfikacji warunków zamówienia") == 4
    assert map_text_to_powod_id("modyfikacji treści SWZ") == 5
