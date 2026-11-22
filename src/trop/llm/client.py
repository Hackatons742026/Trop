"""OpenAI-compatible LLM client stub (httpx). Used only when a profile is enabled.

Default profile is ``none`` — never required for ``trop run``. Missing API key
or any transport/API failure leaves the rules-only payload unchanged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from trop.settings import _repo_root

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmProfile:
    """Resolved LLM profile from ``config/llm.yaml`` (+ optional app settings)."""

    name: str
    enabled: bool
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_env: str = "TROP_LLM__API_KEY"
    timeout_s: int = 30
    max_fields: int = 8


def load_llm_config(path: Path | None = None) -> dict[str, Any]:
    """Load ``config/llm.yaml``; return empty dict if missing."""
    cfg_path = path or Path(os.environ.get("TROP_LLM_CONFIG", "config/llm.yaml"))
    if not cfg_path.is_file():
        alt = _repo_root() / cfg_path
        if alt.is_file():
            cfg_path = alt
        else:
            return {}
    with cfg_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def resolve_profile(
    *,
    config: dict[str, Any] | None = None,
    profile_name: str | None = None,
) -> LlmProfile:
    """Resolve active profile. ``default_profile: none`` → disabled stub."""
    cfg = config if config is not None else load_llm_config()
    name = profile_name or str(cfg.get("default_profile") or "none")
    profiles = cfg.get("profiles") or {}
    raw = profiles.get(name) if isinstance(profiles, dict) else None
    if not isinstance(raw, dict):
        # Unknown name → treat as none (safe).
        return LlmProfile(name=name, enabled=False)

    enabled = bool(raw.get("enabled", False)) and name != "none"
    api_key_env = str(raw.get("api_key_env") or "TROP_LLM__API_KEY")
    api_key = os.environ.get(api_key_env) or os.environ.get("TROP_LLM__API_KEY")
    # Empty string counts as missing.
    if api_key is not None and not str(api_key).strip():
        api_key = None

    return LlmProfile(
        name=name,
        enabled=enabled,
        base_url=(str(raw["base_url"]) if raw.get("base_url") else None),
        model=(str(raw["model"]) if raw.get("model") else None),
        api_key=api_key,
        api_key_env=api_key_env,
        timeout_s=int(raw.get("timeout_s") or 30),
        max_fields=int(raw.get("max_fields") or 8),
    )


def _chat_completion(
    profile: LlmProfile,
    *,
    system: str,
    user: str,
) -> str | None:
    """POST ``/chat/completions``; return assistant text or None on any failure."""
    if not profile.base_url or not profile.model or not profile.api_key:
        return None
    url = profile.base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {profile.api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": profile.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
    }
    try:
        with httpx.Client(timeout=profile.timeout_s) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        content = msg.get("content")
        return str(content) if content is not None else None
    except Exception as exc:  # noqa: BLE001 — never break rules-only path
        logger.warning("LLM call failed (rules-only result kept): %s", exc)
        return None


def maybe_assist(
    payload: dict[str, Any],
    *,
    document_text: str | None = None,
    class_id: str | None = None,
    profile: LlmProfile | None = None,
) -> dict[str, Any]:
    """Optionally enrich ``payload``. Profile ``none`` / missing key → unchanged.

    The stub does **not** invent values when disabled. When enabled, a failed
    or incomplete response returns the original rules-only dict intact.
    """
    active = profile if profile is not None else resolve_profile()
    if not active.enabled or active.name == "none":
        return payload
    if not active.api_key:
        logger.info(
            "LLM profile %r enabled but %s unset — keeping rules-only JSON",
            active.name,
            active.api_key_env,
        )
        return payload
    if not active.base_url or not active.model:
        logger.info(
            "LLM profile %r missing base_url/model — keeping rules-only JSON",
            active.name,
        )
        return payload

    # No vetted merge path exists yet, so a reply could never reach the scored
    # JSON. Don't send document text to an external API (cost, latency, data
    # exposure) for a result that would be discarded. When a merge is
    # implemented, call _chat_completion() here and merge its JSON.
    global _warned_no_merge
    if not _warned_no_merge:
        _warned_no_merge = True
        logger.warning(
            "LLM profile %r is enabled, but LLM assist has no merge step yet — "
            "no request is sent and the rules-only JSON is kept",
            active.name,
        )
    return payload


_warned_no_merge = False
