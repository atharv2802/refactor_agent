"""Application settings.

Centralised, validated configuration loaded from environment / ``.env``.
Everything that varies by deployment (keys, model, limits, voice) lives here so
no other module reads ``os.environ`` directly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Vapi (voice mode)
    vapi_public_key: str = ""
    vapi_webhook_secret: str = ""
    server_url: str = "http://localhost:8000"

    # Voice rendering
    voice_provider: str = "11labs"
    # ElevenLabs requires an actual voice ID, not a display name.
    # 21m00Tcm4TlvDq8ikWAM = "Rachel" (default ElevenLabs voice).
    voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # Output
    output_dir: str = "./results"

    # Engine / safety limits
    max_turns: int = 50
    max_tool_calls: int = 10
    max_response_chars: int = 500

    # Identity injected into the system prompt (hardcoded provider for the MVP).
    provider_name: str = "Northstar Medical Group"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (single source of truth)."""
    return Settings()
