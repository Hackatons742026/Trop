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


def _pelnomocnictwo_payload() -> dict:
    text = (TEXT / "pelnomocnictwo_smoke.txt").read_text(encoding="utf-8")
    payload = extract_payload(text, _spec("pelnomocnictwo"))
    assert validate_payload(payload, _spec("pelnomocnictwo").schema)
    return payload


def test_pelnomocnicy_ignores_lowercase_prose() -> None:
    """A global (?i) used to turn 'udziela pełnomocnictwa' into an attorney."""
    names = [p["imie_nazwisko"] for p in _pelnomocnictwo_payload()["pelnomocnicy"]]
    assert names == ["Jan Kowalski"]  # "adw. Janowi Kowalskiemu" in the text


def test_pelnomocnicy_block_keeps_pesel() -> None:
    """The block used to end at the word PESEL, cutting off the number."""
    pel = _pelnomocnictwo_payload()["pelnomocnicy"]
    assert [p["pesel"] for p in pel] == ["80010112345"]


def test_pelnomocnicy_header_layout_skips_untitled_names() -> None:
    """Layout from the official training set: plural header, titled names."""
    text = (
        "P E Ł N O M O C N I C T W O\n"
        "Mocodawca Hartica Serwis S.A.\n"
        "Pełnomocnicy adw. Bartosz Szymanski, nr wpisu WA 33513\n"
        "r. pr. Cezary Wierzbicki, nr wpisu WA 16243\n"
        "Zamawiający Eurosept Infrastruktura S.A.\n"
        "Zakres Mocodawca upoważniam wskazanym pełnomocnikom do:\n"
        "• zastępowania Wykonawcy przed Krajową Izbą Odwoławczą,\n"
        "Data 03.09.2026\n"
    )
    pel = extract_payload(text, _spec("pelnomocnictwo"))["pelnomocnicy"]
    assert [p["imie_nazwisko"] for p in pel] == ["Bartosz Szymanski", "Cezary Wierzbicki"]


def test_podpisujacy_uses_its_own_block() -> None:
    """List fields used to ignore extractor ``block:``; signatures were lost."""
    mocodawca = _pelnomocnictwo_payload()["mocodawca"]
    assert mocodawca[0]["podpisujacy"] == [{"imie_nazwisko": "Anna Nowak"}]


def test_podpisujacy_after_dotted_signature_lines() -> None:
    text = (
        "PEŁNOMOCNICTWO\n"
        "Mocodawcą jest Zarendel Automatyka sp. j., KRS 9999063951.\n"
        "Mocodawca ustanawiam pełnomocnikiem r. pr. Cezary Walczak.\n"
        "§ 3. Postępowanie\n"
        "Mocodawca:\n"
        ".............................\n"
        "Za Zarendel Automatyka sp. j.\n"
        "Halina Mazurkiewicz\n"
        "Członek Zarządu\n"
        ".............................\n"
        "Sławomir Szulc\n"
        "Prokurent\n"
        "Pełnomocnictwo przyjmuję:\n"
        ".............................\n"
        "r. pr. Cezary Walczak\n"
    )
    mocodawca = extract_payload(text, _spec("pelnomocnictwo"))["mocodawca"]
    names = [p["imie_nazwisko"] for p in mocodawca[0]["podpisujacy"]]
    assert names == ["Halina Mazurkiewicz", "Sławomir Szulc"]


def _mocodawca_typ(text: str) -> str | None:
    mocodawca = extract_payload(text, _spec("pelnomocnictwo"))["mocodawca"]
    return mocodawca[0]["data"]["typ"] if mocodawca else None


def test_typ_sole_trader_with_nip_is_osoba_fizyczna() -> None:
    text = (
        "PEŁNOMOCNICTWO\n"
        "Ja, niżej podpisany Jarosław Dudek, prowadzący działalność gospodarczą pod firmą\n"
        "DUDEK-TECH Jarosław Dudek, NIP 9994150873, wpisany do Centralnej Ewidencji i\n"
        "Informacji o Działalności Gospodarczej, niniejszym udzielam pełnomocnictwa:\n"
        "adw. Jan Kowalski\n"
    )
    assert _mocodawca_typ(text) == "osoba_fizyczna"


def test_typ_legal_form_suffix_is_osoba_prawna() -> None:
    """The old pattern's trailing \\b after 'S.A.' could never match."""
    text = (
        "PEŁNOMOCNICTWO\n"
        "Mocodawca: Testowa S.A. z siedzibą w Gdańsku\n"
        "udziela pełnomocnictwa adw. Jan Kowalski\n"
    )
    assert _mocodawca_typ(text) == "osoba_prawna"


def test_typ_is_not_invented_without_cues() -> None:
    text = (
        "PEŁNOMOCNICTWO\n"
        "Mocodawca: Firma Testowa\n"
        "udziela pełnomocnictwa adw. Jan Kowalski\n"
    )
    assert _mocodawca_typ(text) is None


def test_pelnomocnik_name_requires_capitalised_tokens() -> None:
    text = (
        "Odwołujący: Firma Testowa S.A.\n"
        "Działa przez pełnomocnika ustanowionego przez zarząd.\n"
        "Zamawiający: Gmina Testowa\n"
    )
    pel = extract_payload(text, _spec("odwolanie"))["Odwolujacy"][0]["pelnomocnik"]
    assert pel["imie_nazwisko"] is None


def test_pelnomocnik_name_accepts_all_caps_surname() -> None:
    text = (
        "Odwołujący: Firma Testowa S.A.\n"
        "pełnomocnik: adw. Jan KOWALSKI\n"
        "Zamawiający: Gmina Testowa\n"
    )
    pel = extract_payload(text, _spec("odwolanie"))["Odwolujacy"][0]["pelnomocnik"]
    assert pel["imie_nazwisko"] == "Jan Kowalski"


def test_bare_swz_does_not_map_to_powod_4() -> None:
    assert map_text_to_powod_id("dotyczy SWZ") is None
    assert map_text_to_powod_id("specyfikacji warunków zamówienia") == 4
    assert map_text_to_powod_id("modyfikacji treści SWZ") == 5


def test_powod_declensions_and_opz() -> None:
    assert map_text_to_powod_id("czynności wyboru jako najkorzystniejszej oferty") == 2
    assert map_text_to_powod_id("wyborze jako najkorzystniejszej oferty") == 2
    assert map_text_to_powod_id("zaniechania odrzucenia oferty") == 7
    assert map_text_to_powod_id("projektowanych postanowień umowy") == 12
    assert map_text_to_powod_id("Przedmiotu Zamówienia (OPZ)") == 11
