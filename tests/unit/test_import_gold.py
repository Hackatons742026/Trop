"""Gold import writes exactly one gold JSON per PDF."""

from __future__ import annotations

import json
from pathlib import Path

from tools.import_gold import split_dane


def test_split_dane_pairs_gold_with_pdfs_only(tmp_path: Path) -> None:
    dane = tmp_path / "dane"
    case = dane / "przyklad_01"
    case.mkdir(parents=True)
    (case / "odwolanie.pdf").write_bytes(b"%PDF")
    (case / "odwolanie.json").write_text('{"a": 1}', encoding="utf-8")
    (case / "potwierdzenie_przelewu.pdf").write_bytes(b"%PDF")
    (case / "przelew.json").write_text('{"b": 2}', encoding="utf-8")
    (dane / "negatywne").mkdir()
    (dane / "negatywne" / "wyrok.pdf").write_bytes(b"%PDF")

    input_dir, gold_dir = tmp_path / "input", tmp_path / "gold"
    pdfs, golds = split_dane(dane, input_dir, gold_dir)

    gold_files = sorted(p.relative_to(gold_dir).as_posix() for p in gold_dir.rglob("*.json"))
    assert gold_files == [
        "negatywne/wyrok.json",
        "przyklad_01/odwolanie.json",
        "przyklad_01/potwierdzenie_przelewu.json",
    ]
    assert (pdfs, golds) == (3, 3)
    assert json.loads((gold_dir / "przyklad_01/potwierdzenie_przelewu.json").read_text()) == {
        "b": 2
    }
    assert json.loads((gold_dir / "negatywne/wyrok.json").read_text()) == {}
