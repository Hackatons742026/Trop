"""Optional LLM assist (off by default; profile ``none`` = rules-only)."""

from trop.llm.client import (
    LlmProfile,
    load_llm_config,
    maybe_assist,
    resolve_profile,
)

__all__ = [
    "LlmProfile",
    "load_llm_config",
    "maybe_assist",
    "resolve_profile",
]
