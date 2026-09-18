"""Application configuration loaded from environment variables.

All values are validated at startup. If an LLM call is required, both
``LLM_API_KEY`` and ``LLM_BASE_URL`` are mandatory unless ``LLM_PROVIDER=mock``.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    MOCK = "mock"


class Settings(BaseSettings):
    """Centralized, immutable settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- LLM ----
    llm_provider: LLMProvider = Field(default=LLMProvider.MOCK)
    llm_api_key: Optional[str] = Field(default=None)
    llm_model: str = Field(default="gpt-4o-mini")
    llm_base_url: str = Field(default="https://api.openai.com/v1")
    llm_timeout_seconds: float = Field(default=30.0)
    llm_temperature: float = Field(default=0.0)

    # ---- Solver ----
    solver_timeout_seconds: int = Field(default=10)
    solver_msg: bool = Field(default=False)  # set to True to see solver logs

    # ---- Tolerances (matches official 0.01 kWh / 0.01 BDT) ----
    tolerance_kwh: float = Field(default=0.01)
    tolerance_bdt: float = Field(default=0.01)

    # ---- Server ----
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    # ---- Logging ----
    log_level: str = Field(default="INFO")

    # ---- Internal helpers ----
    def require_llm_credentials(self) -> None:
        """Raise if the chosen provider requires network credentials."""
        if self.llm_provider == LLMProvider.OPENAI:
            missing = []
            if not self.llm_api_key:
                missing.append("LLM_API_KEY")
            if not self.llm_base_url:
                missing.append("LLM_BASE_URL")
            if missing:
                raise RuntimeError(
                    f"LLM_PROVIDER=openai requires: {', '.join(missing)}"
                )


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Lazy, cached settings accessor."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Used by tests to pick up environment changes between cases."""
    global _settings
    _settings = None
