"""Application configuration.

All credentials come from environment variables (or a local `.env` file that is
never committed). Nothing here is ever sent to the frontend except the
non-secret fields exposed by `Settings.public_view()`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT.parent / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "OMNIFORGE"
    version: str = "0.1.0"

    # Storage
    data_dir: Path = Field(default=BACKEND_ROOT / ".data", alias="OMNIFORGE_DATA_DIR")
    database_url: str | None = Field(default=None, alias="OMNIFORGE_DATABASE_URL")
    max_upload_mb: int = Field(default=15, alias="OMNIFORGE_MAX_UPLOAD_MB")

    # Key-encryption key (base64, 32 bytes). If absent a dev key file is generated.
    master_key: str | None = Field(default=None, alias="OMNIFORGE_MASTER_KEY")

    # CORS
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173", alias="OMNIFORGE_CORS_ORIGINS"
    )

    # AI providers: auto | gemini | openai | local
    ai_provider: str = Field(default="auto", alias="AI_PROVIDER")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")
    google_api_key: str | None = Field(default=None, alias="GOOGLE_API_KEY")
    gemini_model: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str | None = Field(default=None, alias="OPENAI_MODEL")
    ai_timeout_s: float = Field(default=30.0, alias="AI_TIMEOUT_S")

    # Default (simulated) identity used when a request carries no role header.
    default_role: str = Field(default="analyst", alias="OMNIFORGE_DEFAULT_ROLE")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'omniforge.db').as_posix()}"

    @property
    def gemini_key(self) -> str | None:
        return self.gemini_api_key or self.google_api_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def public_view(self) -> dict:
        """Non-secret configuration safe to show in the UI."""
        return {
            "app_name": self.app_name,
            "version": self.version,
            "ai_provider_preference": self.ai_provider,
            "gemini_configured": bool(self.gemini_key),
            "gemini_model": self.gemini_model,
            "openai_compatible_configured": bool(self.openai_api_key and self.openai_model),
            "openai_base_url": self.openai_base_url,
            "openai_model": self.openai_model,
            "max_upload_mb": self.max_upload_mb,
            "master_key_source": "environment" if self.master_key else "local dev key file",
            "default_role": self.default_role,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
