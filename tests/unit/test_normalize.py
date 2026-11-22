"""Unit tests for normaliser functions."""

from __future__ import annotations

import pytest

from trop.normalize import (
    account_number,
    amount_pl,
    apply_normalizers,
    bzp_number,
    collapse_ws,
    company_name,
    date_pl,
    digits_only,
    iban_as_printed,
    krs_pad10,
    nominative,
    person_name,
    place_name,
    strip_titles,
    ted_number,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("13.10.2025", "2025-10-13"),
        ("13/10/2025", "2025-10-13"),
        ("2025-10-13", "2025-10-13"),
        ("1 stycznia 2025", "2025-01-01"),
        ("13 października 2025 r.", "2025-10-13"),
        ("", None),
        (None, None),
        ("nie-data", None),
    ],
)
def test_date_pl(raw: object, expected: str | None) -> None:
    assert date_pl(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 234,56", 1234.56),
        ("1234.56", 1234.56),
        ("50,00 PLN", 50.0),
        ("10.00", 10.0),
        ("", None),
        (None, None),
    ],
)
def test_amount_pl(raw: object, expected: float | None) -> None:
    assert amount_pl(raw) == expected


def test_iban_as_printed_keeps_pl() -> None:
    assert iban_as_printed("PL 61 0101 0101 0008 1362 2310 0000") == (
        "PL 61 0101 0101 0008 1362 2310 0000"
    )
    assert iban_as_printed("60101010100081362231000000") == "60101010100081362231000000"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PL39203888965989833490230983", "39203888965989833490230983"),
        ("PL39 2038 8896 5989 8334 9023 0983", "39203888965989833490230983"),
        ("34 1240 1111 0246 3566 1382 2453", "34124011110246356613822453"),
        ("39203888965989833490230983", "39203888965989833490230983"),
        ("12345", None),
        (None, None),
    ],
)
def test_account_number(raw: object, expected: str | None) -> None:
    assert account_number(raw) == expected


def test_digits_only_and_krs() -> None:
    assert digits_only("999-067-80-35") == "9990678035"
    assert krs_pad10("12345") == "0000012345"
    assert krs_pad10("9999669444") == "9999669444"
    # OCR letter-O inside KRS digit run.
    assert krs_pad10("9994328o29") == "9994328029"


def test_person_and_place_ocr_repairs() -> None:
    assert person_name("Lukasz Sosnowski") == "Łukasz Sosnowski"
    assert person_name("Szymon Zawadżki") == "Szymon Zawadzki"
    assert place_name("Lódź") == "Łódź"
    assert company_name("Orbisol Budownictwo Sp. z 0.0.") == "Orbisol Budownictwo Sp. z o.o."


def test_bzp_and_ted() -> None:
    assert bzp_number("2026 / BZP 00999778") == "2026/BZP00999778"
    assert bzp_number("2026/BZP00999778/01") == "2026/BZP00999778/01"
    assert bzp_number("2025/BZP00998520") is None
    assert ted_number("999073-2026") == "999073-2026"
    assert ted_number("2026/S 112-383751") == "383751-2026"
    # Historical comparisons in appeal bodies must not become numer_ted.
    assert ted_number("2025/S 112-383751") is None


def test_collapse_and_titles() -> None:
    assert collapse_ws("  a   b  ") == "a b"
    assert strip_titles("adw. Bartosz Szymanski") == "Bartosz Szymanski"
    assert strip_titles("r. pr. Anna Nowak") == "Anna Nowak"


def test_nominative_passthrough() -> None:
    # Heuristic / Morfeusz — at least does not invent empty
    assert nominative("Bartosz Szymanski") == "Bartosz Szymanski"
    assert nominative(None) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Janowi Kowalskiemu", "Jan Kowalski"),
        ("Markowi Zawadzkiemu", "Marek Zawadzki"),
        ("Pawłowi Długiemu", "Paweł Długi"),
        ("Tomaszowi Dudkowi", "Tomasz Dudek"),
        ("Piotrowi Nowakowi", "Piotr Nowak"),
        ("Michałowi Szulcowi", "Michał Szulc"),
        ("JANOWI KOWALSKIEMU", "JAN KOWALSKI"),
        ("Kowalskiej", "Kowalska"),
        # Nominative input stays as written.
        ("Weronika Kaczmarek", "Weronika Kaczmarek"),
        ("Jan Nowak", "Jan Nowak"),
        ("Cezary Wierzbicki", "Cezary Wierzbicki"),
    ],
)
def test_nominative_heuristics_without_morfeusz(monkeypatch, raw: str, expected: str) -> None:
    monkeypatch.setattr("trop.normalize.fns._MORFEUSZ", None)
    assert nominative(raw) == expected


def test_morfeusz_prefers_proper_name_lemma(monkeypatch) -> None:
    class FakeMorfeusz:
        def analyse(self, token: str):
            # First analysis is an adjective reading; old code returned it.
            return [
                (0, 1, ("Janowi", "janowy", "adj:sg:dat:m1:pos", [], [])),
                (0, 1, ("Janowi", "Jan:Sm1", "subst:sg:dat:m1", ["imię"], [])),
            ]

    monkeypatch.setattr("trop.normalize.fns._MORFEUSZ", FakeMorfeusz())
    assert nominative("Janowi") == "Jan"


def test_apply_normalizers_chain() -> None:
    assert apply_normalizers("  13.10.2025  ", ["collapse_ws", "date_pl"]) == "2025-10-13"
    assert apply_normalizers("xxx", ["date_pl"]) is None
