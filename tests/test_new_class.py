"""Config-only class discovery (P2/P3): no Python module required to register."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from trop.cli import app
from trop.registry.loader import (
    clear_registry_cache,
    default_classes_dir,
    iter_class_dirs,
    load_class_spec,
    load_classes,
)

runner = CliRunner()


def setup_function() -> None:
    clear_registry_cache()


def teardown_function() -> None:
    clear_registry_cache()


def test_template_dir_is_not_registered() -> None:
    root = default_classes_dir()
    assert (root / "_template" / "class.yaml").is_file()
    ids = {s.id for s in load_classes()}
    assert "_template" not in ids
    assert all(not p.name.startswith("_") for p in iter_class_dirs(root))


def test_demo_przystapienie_is_underscore_docs_only() -> None:
    """Demo lives under ``_demo_przystapienie`` and must not register."""
    root = default_classes_dir()
    demo_dir = root / "_demo_przystapienie"
    assert (demo_dir / "class.yaml").is_file()
    assert (demo_dir / "schema.json").is_file()
    assert not (demo_dir / "__init__.py").exists()
    ids = {s.id for s in load_classes()}
    assert "demo_przystapienie" not in ids
    assert "_demo_przystapienie" not in ids
    # Official three classes only by default (no extra live demos).
    assert ids == {"odwolanie", "pelnomocnictwo", "przelew"}


def test_dummy_class_loads_with_zero_code_change(tmp_path: Path) -> None:
    """Drop class.yaml into a folder → load_classes picks it up (no imports)."""
    class_dir = tmp_path / "dummy_zero_code"
    class_dir.mkdir()
    (class_dir / "class.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "dummy_zero_code",
                "label": "Dummy Zero Code",
                "detect": {
                    "threshold": 3.0,
                    "margin": 1.0,
                    "keywords": [{"pattern": "(?i)\\bdummy\\b", "weight": 5.0}],
                },
                "fields": [],
                "lists": [],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (class_dir / "schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "dummy_zero_code",
                "type": "object",
                "properties": {},
            }
        ),
        encoding="utf-8",
    )
    # Underscore scratch folder must be ignored even with class.yaml present.
    scratch = tmp_path / "_scratch"
    scratch.mkdir()
    (scratch / "class.yaml").write_text(
        "id: scratch\nlabel: Scratch\ndetect:\n  keywords: []\n",
        encoding="utf-8",
    )

    clear_registry_cache()
    specs = load_classes(str(tmp_path))
    ids = {s.id for s in specs}
    assert ids == {"dummy_zero_code"}
    spec = load_class_spec(class_dir)
    assert spec.label == "Dummy Zero Code"
    assert spec.detect.threshold == 3.0


def test_new_class_cli_copies_template(tmp_path: Path, monkeypatch) -> None:
    # Build a miniature classes tree with only _template.
    classes = tmp_path / "classes"
    template = classes / "_template"
    template.mkdir(parents=True)
    (template / "class.yaml").write_text(
        "id: __CLASS_ID__\nlabel: \"__CLASS_LABEL__\"\ndetect:\n  keywords: []\n",
        encoding="utf-8",
    )
    (template / "schema.json").write_text(
        '{"$id": "trop://classes/__CLASS_ID__/schema.json", "title": "__CLASS_ID__"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "trop.cli.default_classes_dir",
        lambda: classes,
    )
    result = runner.invoke(app, ["new-class", "fresh_demo", "--label", "Fresh Demo"])
    assert result.exit_code == 0, result.output
    dest = classes / "fresh_demo"
    assert dest.is_dir()
    text = (dest / "class.yaml").read_text(encoding="utf-8")
    assert "id: fresh_demo" in text
    assert "Fresh Demo" in text
    assert "__CLASS_ID__" not in text
    schema = (dest / "schema.json").read_text(encoding="utf-8")
    assert "fresh_demo" in schema
    assert "__CLASS_ID__" not in schema

    clear_registry_cache()
    specs = load_classes(str(classes))
    assert {s.id for s in specs} == {"fresh_demo"}
