from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_config_dir() -> Path:
    """Resolve bundled configuration in wheels and repository configuration in checkouts."""
    package_config = Path(__file__).resolve().parent / "config"
    if package_config.is_dir():
        return package_config
    return Path(__file__).resolve().parents[2] / "config"


class MicrosoftSettings(BaseModel):
    endpoint: HttpUrl | None = None
    api_key: SecretStr | None = None
    api_version: str = "2025-10-15"


class ElevenLabsSettings(BaseModel):
    api_key: SecretStr | None = None
    base_url: HttpUrl = HttpUrl("https://api.elevenlabs.io")
    zero_retention: bool = True


class GroqSettings(BaseModel):
    api_key: SecretStr | None = None
    base_url: HttpUrl = HttpUrl("https://api.groq.com/openai/v1")


class SecuritySettings(BaseModel):
    auth_mode: Literal["none", "bearer", "oidc"] = "bearer"
    bearer_token: SecretStr | None = None
    require_https_sources: bool = True
    allow_private_urls: bool = False
    max_redirects: int = Field(default=3, ge=0, le=10)
    allowed_source_hosts: list[str] = Field(default_factory=list)


class ResultStoreSettings(BaseModel):
    backend: Literal["disabled", "memory", "s3"] = "disabled"
    cursor_secret: SecretStr | None = None
    ttl_seconds: int = Field(default=86400, ge=60)
    s3_bucket: str | None = None
    s3_endpoint_url: HttpUrl | None = None
    s3_region: str = "fr-par"
    s3_prefix: str = "transcripts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OT_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["dev", "test", "prod"] = "prod"
    host: str = "0.0.0.0"  # noqa: S104
    port: int = Field(default=8000, ge=1, le=65535)
    default_provider: str = "microsoft"
    default_model: str = "MAI-Transcribe-2"
    request_timeout_seconds: int = Field(default=900, ge=1)
    provider_timeout_seconds: int = Field(default=600, ge=1)
    source_download_timeout_seconds: int = Field(default=120, ge=1)
    max_audio_size_mb: int = Field(default=500, ge=1)
    max_audio_duration_seconds: int = Field(default=21600, ge=1)
    max_request_cost_usd: float | None = Field(default=None, gt=0)
    max_inline_text_chars: int = Field(default=100000, ge=1)
    max_inline_segments: int = Field(default=1000, ge=1)
    max_inline_response_bytes: int = Field(default=400000, ge=1000)
    config_dir: Path = Field(default_factory=_default_config_dir)
    microsoft: MicrosoftSettings = MicrosoftSettings()
    elevenlabs: ElevenLabsSettings = ElevenLabsSettings()
    groq: GroqSettings = GroqSettings()
    security: SecuritySettings = SecuritySettings()
    result_store: ResultStoreSettings = ResultStoreSettings()

    @property
    def max_audio_bytes(self) -> int:
        return self.max_audio_size_mb * 1024 * 1024

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.security.auth_mode == "bearer" and self.security.bearer_token is None:
            raise ValueError("OT_SECURITY__BEARER_TOKEN is required for bearer auth")
        if self.security.auth_mode == "oidc":
            raise ValueError("OIDC is reserved for v0.2; use bearer or none in v0.1")
        if self.environment == "prod" and self.security.auth_mode == "none":
            raise ValueError("unauthenticated mode is not allowed in production")
        if self.result_store.backend != "disabled" and self.result_store.cursor_secret is None:
            raise ValueError(
                "OT_RESULT_STORE__CURSOR_SECRET is required when result storage is enabled"
            )
        if self.result_store.backend == "s3" and not self.result_store.s3_bucket:
            raise ValueError("OT_RESULT_STORE__S3_BUCKET is required for the S3 result store")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
