"""Class config typos are reported instead of silently matching nothing."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from trop.cli import app
from trop.registry.loader import (
    clear_registry_cache,
    load_classes,
    load_classes_report,
    validate_class_spec,
)

runner = CliRunner()

BROKEN = {
    "id": "broken",
    "label": "Broken",
    "detect": {"keywords": [{"pattern": "(?i)ok", "weight": 1.0}]},
    "blocks": [{"id": "body", "start": "(unclosed", "end": None}],
    "fields": [
        {
            "path": "a.b",
            "extractors": [
                {"type": "regx", "pattern": "x"},
                {"type": "regex", "pattern": "[a-", "normalize": ["date_PL"]},
                {"type": "label", "labels": ["Kwota"], "value_pattern": "(\\d+)(?i)"},
                {"type": "regex", "pattern": "y", "block": "bodyy"},
            ],
        }
    ],
    "lists": [],
}


def _write_class(root: Path, data: dict) -> None:
    folder = root / data["id"]
    folder.mkdir(parents=True)
    (folder / "class.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def setup_function() -> None:
    clear_registry_cache()


def teardown_function() -> None:
    clear_registry_cache()


def test_official_classes_have_no_problems() -> None:
    specs = load_classes()
    assert specs
    for spec in specs:
        assert validate_class_spec(spec) == [], spec.id


def test_broken_class_problems_are_all_reported(tmp_path: Path) -> None:
    _write_class(tmp_path, BROKEN)
    specs, problems = load_classes_report(tmp_path)

    assert [s.id for s in specs] == ["broken"]  # still loads; run degrades gracefully
    text = "\n".join(problems)
    assert "blocks[body].start: invalid regex" in text
    assert "unknown extractor type 'regx'" in text
    assert "extractors[1].pattern: invalid regex" in text
    assert "unknown normalizer 'date_PL'" in text
    assert "extractors[2].value_pattern: invalid regex" in text  # flag not at start
    assert "unknown block 'bodyy'" in text
    assert len(problems) == 6


def test_schema_checked_once_at_load(tmp_path: Path, monkeypatch) -> None:
    from jsonschema import Draft202012Validator

    from trop.io.schema_validate import validated_or_empty

    spec = next(s for s in load_classes() if s.id == "przelew")
    assert spec.validator is not None

    def boom(*_a, **_k):
        raise AssertionError("schema re-checked per document")

    monkeypatch.setattr(Draft202012Validator, "check_schema", boom)
    required = spec.schema["properties"]["przelew_bankowy"]["required"]
    payload = {"przelew_bankowy": dict.fromkeys(required)}
    assert validated_or_empty(payload, spec.schema, validator=spec.validator) == payload


def test_broken_schema_fails_class_load(tmp_path: Path) -> None:
    _write_class(tmp_path, {**BROKEN, "id": "bad_schema", "blocks": [], "fields": []})
    (tmp_path / "bad_schema" / "schema.json").write_text('{"type": 5}', encoding="utf-8")
    specs, problems = load_classes_report(tmp_path)
    assert specs == ()
    assert any("bad_schema/class.yaml: failed to load" in p for p in problems)


def test_classes_list_exits_nonzero_on_problems(tmp_path: Path, monkeypatch) -> None:
    _write_class(tmp_path, BROKEN)
    monkeypatch.setattr("trop.registry.loader.default_classes_dir", lambda: tmp_path)
    monkeypatch.setattr("trop.cli.default_classes_dir", lambda: tmp_path)

    result = runner.invoke(app, ["classes", "list"])

    assert result.exit_code == 1
    assert "unknown normalizer 'date_PL'" in result.output
