"""Application settings: YAML defaults + environment overrides."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_workers() -> int:
    """Sensible default for the 2 vCPU judge VM (workers == vCPU when cpu <= 2)."""
    cpu = os.cpu_count() or 2
    if cpu <= 2:
        return max(1, cpu)
    return max(1, cpu // 2)


def _repo_root() -> Path:
    """Resolve repo root from package location (src/trop → repo / /opt/solution)."""
    return Path(__file__).resolve().parents[2]


class OcrSettings(BaseModel):
    enabled: bool = True
    min_chars: int = 40
    min_printable_ratio: float = 0.9
    max_pages: int | None = 20
    engine: str = "rapidocr"
    backend: str = "onnxruntime"


class LlmSettings(BaseModel):
    enabled: bool = False
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    timeout_s: int = 30


class PathSettings(BaseModel):
    input_dir: Path = Path("input")
    output_dir: Path = Path("output")
    evidence_dir: Path | None = None


class LoggingSettings(BaseModel):
    level: str = "INFO"


class Settings(BaseSettings):
    """Runtime settings for TROP.

    Precedence: CLI args > env (TROP_*) > config/app.yaml > code defaults.
    """

    model_config = SettingsConfigDict(
        env_prefix="TROP_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    config: Path = Field(default=Path("config/app.yaml"))
    input_dir: Path = Field(default=Path("input"))
    output_dir: Path = Field(default=Path("output"))
    # None / empty → no evidence sidecars unless CLI ``--evidence`` is set.
    evidence_dir: Path | None = Field(default=None)
    workers: int | None = 2
    dpi: int = 200
    max_dpi: int = 250
    max_pages: int | None = 40
    log_level: str = "INFO"
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    llm: LlmSettings = Field(default_factory=LlmSettings)

    @field_validator("workers", mode="before")
    @classmethod
    def _empty_workers(cls, value: object) -> object:
        if value == "" or value is None:
            return None
        return value

    @field_validator("evidence_dir", mode="before")
    @classmethod
    def _empty_evidence_dir(cls, value: object) -> object:
        if value is None or value == "" or value == "null":
            return None
        return value

    def resolved_workers(self) -> int:
        if self.workers is not None and self.workers > 0:
            return self.workers
        return _default_workers()

    def resolved_dpi(self) -> int:
        dpi = max(72, int(self.dpi))
        cap = max(72, int(self.max_dpi))
        return min(dpi, cap)


def load_yaml_config(path: Path | None = None) -> dict:
    """Load config/app.yaml if present; return empty dict otherwise."""
    cfg_path = path or Path(os.environ.get("TROP_CONFIG", "config/app.yaml"))
    if not cfg_path.is_file():
        # Try relative to repo root when cwd differs.
        alt = _repo_root() / cfg_path
        if alt.is_file():
            cfg_path = alt
        else:
            return {}
    with cfg_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        return {}
    return data


def settings_from_yaml(yaml_data: dict) -> dict:
    """Flatten nested YAML into Settings kwargs."""
    kwargs: dict = {}
    paths = yaml_data.get("paths") or {}
    if "input_dir" in paths:
        kwargs["input_dir"] = paths["input_dir"]
    if "output_dir" in paths:
        kwargs["output_dir"] = paths["output_dir"]
    if "evidence_dir" in paths:
        ev = paths["evidence_dir"]
        kwargs["evidence_dir"] = None if ev in (None, "", "null") else ev
    if "workers" in yaml_data:
        kwargs["workers"] = yaml_data["workers"]
    if "dpi" in yaml_data:
        kwargs["dpi"] = yaml_data["dpi"]
    if "max_dpi" in yaml_data:
        kwargs["max_dpi"] = yaml_data["max_dpi"]
    if "max_pages" in yaml_data:
        kwargs["max_pages"] = yaml_data["max_pages"]
    logging = yaml_data.get("logging") or {}
    if "level" in logging:
        kwargs["log_level"] = logging["level"]
    ocr = yaml_data.get("ocr") or {}
    if ocr:
        kwargs["ocr"] = OcrSettings.model_validate(ocr)
    llm = yaml_data.get("llm") or {}
    if llm:
        kwargs["llm"] = LlmSettings.model_validate(llm)
    return kwargs


@lru_cache
def get_settings() -> Settings:
    """Cached settings: YAML first, then env overrides via BaseSettings."""
    yaml_data = load_yaml_config()
    base = settings_from_yaml(yaml_data)
    # BaseSettings still applies env on top of these defaults.
    return Settings(**base)


def clear_settings_cache() -> None:
    get_settings.cache_clear()
