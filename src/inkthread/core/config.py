"""Runtime configuration (spec 10 § 1).

Built once at startup and validated there, so a bad configuration fails the boot rather than the
first request. Secrets are `SecretStr`, so they never print.
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_PLACEHOLDER_SHAS = frozenset({"", "unknown", "none", "null"})


class LlmMode(StrEnum):
    """How the agent stages reach a model (spec 05 § 2)."""

    LIVE = "live"
    REPLAY = "replay"
    OFF = "off"


class BlobStoreKind(StrEnum):
    """Where PDFs, page images and page geometry live (spec 08 § 2)."""

    LOCAL = "local"
    R2 = "r2"


class Settings(BaseSettings):
    """Every variable the service reads. Field names map to upper-case environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    port: int = Field(default=8000, ge=1, le=65535)

    database_url: str = Field(min_length=1)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    admin_token: SecretStr | None = None
    metrics_token: SecretStr | None = None

    blob_store: BlobStoreKind = BlobStoreKind.LOCAL
    blob_root: Path = Path("./var/blobs")
    r2_account_id: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    r2_endpoint: str | None = None
    r2_prefix: str = "inkthread/"

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model_primary: str = "nvidia/nemotron-3-super-120b-a12b:free"
    openrouter_model_fast: str = "google/gemma-4-31b-it:free"
    openrouter_model_fallback: str = "google/gemma-4-26b-a4b-it:free"
    openrouter_site_url: str = "http://localhost:3000"
    openrouter_app_name: str = "inkthread"

    llm_mode: LlmMode = LlmMode.LIVE
    llm_max_requests_per_document: int = Field(default=8, ge=0)
    llm_daily_request_cap: int = Field(default=40, ge=0)
    llm_account_reserve: int = Field(default=10, ge=0)
    llm_max_tokens: int = Field(default=12000, ge=256)
    llm_timeout_s: float = Field(default=90.0, gt=0)

    max_upload_bytes: int = Field(default=15 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=40, gt=0)
    max_queue: int = Field(default=10, gt=0)
    uploads_per_hour: int = Field(default=5, gt=0)
    retention_days: int = Field(default=7, gt=0)
    job_timeout_s: float = Field(default=900.0, gt=0)
    read_timeout_s: float = Field(default=300.0, gt=0)
    read_memory_limit_mb: int = Field(default=0, ge=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.openrouter_model_primary == self.openrouter_model_fast:
            msg = (
                "OPENROUTER_MODEL_PRIMARY and OPENROUTER_MODEL_FAST must differ: "
                "the verifier must not be the model that made the claims"
            )
            raise ValueError(msg)
        if self.app_env == "production" and "*" in self.cors_origins:
            msg = "CORS_ORIGINS='*' is refused in production; list the allowed origins"
            raise ValueError(msg)
        if self.blob_store is BlobStoreKind.R2:
            missing = [
                name
                for name, value in (
                    ("R2_ACCOUNT_ID", self.r2_account_id),
                    ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
                    ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
                    ("R2_BUCKET", self.r2_bucket),
                    ("R2_ENDPOINT", self.r2_endpoint),
                )
                if not value
            ]
            if missing:
                msg = f"BLOB_STORE=r2 needs {', '.join(missing)}"
                raise ValueError(msg)
        if self.llm_mode is LlmMode.LIVE and self.openrouter_api_key is None:
            msg = "LLM_MODE=live needs OPENROUTER_API_KEY (use replay or off without one)"
            raise ValueError(msg)
        return self

    @property
    def commit_sha(self) -> str:
        """The deployed commit: COMMIT_SHA, RENDER_GIT_COMMIT, GITHUB_SHA, else `unknown`."""
        for name in ("COMMIT_SHA", "RENDER_GIT_COMMIT", "GITHUB_SHA"):
            value = os.environ.get(name, "").strip()
            if value.lower() not in _PLACEHOLDER_SHAS:
                return value
        return "unknown"

    @property
    def is_production(self) -> bool:
        """Whether this is the deployed service."""
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings, read from the environment once."""
    return Settings()
