"""Settings precedence: init kwargs > env (TROP_*) > config/app.yaml > defaults."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from trop.settings import Settings, clear_settings_cache, get_settings


@pytest.fixture
def app_yaml(tmp_path: Path, monkeypatch) -> Iterator[Path]:
    cfg = tmp_path / "app.yaml"
    cfg.write_text(
        "workers: 2\n"
        "dpi: 200\n"
        "max_pages: 12\n"
        "paths:\n"
        "  evidence_dir: null\n"
        "ocr:\n"
        "  enabled: true\n"
        "  min_chars: 55\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TROP_CONFIG", str(cfg))
    for var in ("TROP_WORKERS", "TROP_DPI", "TROP_MAX_PAGES", "TROP_EVIDENCE_DIR"):
        monkeypatch.delenv(var, raising=False)
    clear_settings_cache()
    yield cfg
    clear_settings_cache()


def test_app_yaml_beats_code_defaults(app_yaml: Path) -> None:
    settings = get_settings()
    assert settings.max_pages == 12  # code default is 40
    assert settings.ocr.min_chars == 55


def test_env_overrides_app_yaml(app_yaml: Path, monkeypatch) -> None:
    monkeypatch.setenv("TROP_WORKERS", "7")
    monkeypatch.setenv("TROP_DPI", "111")
    monkeypatch.setenv("TROP_EVIDENCE_DIR", "ev")
    monkeypatch.setenv("TROP_OCR__ENABLED", "false")

    settings = get_settings()

    assert settings.workers == 7
    assert settings.dpi == 111
    assert settings.evidence_dir == Path("ev")
    assert settings.ocr.enabled is False
    assert settings.ocr.min_chars == 55  # sibling key from YAML survives


def test_init_kwargs_beat_env(app_yaml: Path, monkeypatch) -> None:
    monkeypatch.setenv("TROP_WORKERS", "7")
    assert Settings(workers=3).workers == 3
