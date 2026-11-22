"""LLM profile ``none`` leaves rules-only payload intact."""

from __future__ import annotations

from pathlib import Path

import yaml

from trop.llm.client import LlmProfile, load_llm_config, maybe_assist, resolve_profile


def test_default_llm_yaml_profile_is_none() -> None:
    cfg = load_llm_config()
    assert cfg.get("default_profile") == "none"
    profile = resolve_profile(config=cfg)
    assert profile.name == "none"
    assert profile.enabled is False


def test_resolve_none_profile_disabled(tmp_path: Path) -> None:
    path = tmp_path / "llm.yaml"
    path.write_text(
        yaml.dump(
            {
                "default_profile": "none",
                "profiles": {
                    "none": {"enabled": False},
                    "openai_compatible": {
                        "enabled": True,
                        "base_url": "https://example.invalid/v1",
                        "model": "x",
                        "api_key_env": "TROP_LLM__API_KEY",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    cfg = load_llm_config(path)
    p = resolve_profile(config=cfg)
    assert p.name == "none"
    assert not p.enabled


def test_maybe_assist_none_returns_same_object() -> None:
    payload = {"OdwolanieKIO": {"data": None}}
    out = maybe_assist(
        payload,
        document_text="ignored",
        class_id="odwolanie",
        profile=LlmProfile(name="none", enabled=False),
    )
    assert out is payload
    assert out == {"OdwolanieKIO": {"data": None}}


def test_maybe_assist_enabled_without_key_keeps_rules(monkeypatch) -> None:
    monkeypatch.delenv("TROP_LLM__API_KEY", raising=False)
    payload = {"x": 1}
    profile = LlmProfile(
        name="openai_compatible",
        enabled=True,
        base_url="https://example.invalid/v1",
        model="test-model",
        api_key=None,
        api_key_env="TROP_LLM__API_KEY",
    )
    out = maybe_assist(payload, class_id="przelew", profile=profile)
    assert out is payload
    assert out == {"x": 1}


def test_maybe_assist_failure_keeps_rules(monkeypatch) -> None:
    """Transport/API failure must not alter rules-only JSON."""
    payload = {"kwota": 10}
    profile = LlmProfile(
        name="openai_compatible",
        enabled=True,
        base_url="https://127.0.0.1:9/v1",  # nothing listening
        model="test-model",
        api_key="fake-key",
        timeout_s=1,
    )
    out = maybe_assist(payload, document_text="kwota 10", profile=profile)
    assert out == {"kwota": 10}
