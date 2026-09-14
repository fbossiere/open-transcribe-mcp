"""The closed, versioned managed desktop configuration.

This file holds preferences and credential *references*. It never holds an API key, a signed
audio URL, a source history, a phrase hint, or transcript text.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from open_transcribe.domain.audio import RoutingPolicy

SCHEMA_VERSION = 1
"""The only managed schema this build reads or writes."""

CREDENTIAL_NAMESPACE = "open-transcribe-mcp"

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")]
InstallationId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CredentialRef(Closed):
    """A Secret Service lookup, never a secret. Attributes are non-secret by construction."""

    service: str = CREDENTIAL_NAMESPACE
    account: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_namespace(self) -> "CredentialRef":
        if self.service != CREDENTIAL_NAMESPACE:
            raise ValueError(f"credential references must stay in the {CREDENTIAL_NAMESPACE} scope")
        return self


class ManagedProvider(Closed):
    """One provider this installation may use, and where its credentials live."""

    enabled: bool = False
    """A stored key does not authorize a provider; only this flag does."""

    credentials: dict[Identifier, CredentialRef] = Field(default_factory=dict)
    endpoint: AnyHttpUrl | None = None
    api_version: str | None = Field(default=None, max_length=64)
    checked_at: datetime | None = None
    check_outcome: Literal["passed", "failed", "not_supported", "not_tested"] = "not_tested"

    @model_validator(mode="after")
    def validate_endpoint(self) -> "ManagedProvider":
        if self.endpoint is not None and self.endpoint.scheme != "https":
            raise ValueError("provider endpoints must use https")
        return self


class ManagedPrivacy(Closed):
    """Permissions the user granted explicitly. Every default here is the restrictive one."""

    temporary_audio_processing: bool = False
    temporary_audio_ttl_seconds: int = Field(default=3600, ge=60, le=3600)
    cross_provider_fallback: bool = False
    transcript_store: Literal["disabled"] = "disabled"
    """Desktop V1 keeps transcript storage disabled; enabling it is a separate design."""


class ManagedLimits(Closed):
    estimated_cost_threshold_usd: float | None = Field(default=None, gt=0)
    """An estimate threshold, not a billing cap. See `docs/desktop-costs`."""

    max_audio_duration_seconds: int = Field(default=21600, ge=1)
    max_audio_size_mb: int = Field(default=500, ge=1)
    request_timeout_seconds: int = Field(default=900, ge=1)
    provider_timeout_seconds: int = Field(default=600, ge=1)


class ManagedClient(Closed):
    """The single client registration this installation owns."""

    adapter_id: Identifier
    display_name: str = Field(max_length=128)
    server_name: Identifier
    registered_at: datetime | None = None
    registration_fingerprint: str | None = Field(default=None, max_length=128)
    activation: Literal["unverified", "user_confirmed", "observed"] = "unverified"


class ManagedSelection(Closed):
    provider: Identifier | None = None
    model: str | None = Field(default=None, min_length=1, max_length=128)
    routing_policy: RoutingPolicy = RoutingPolicy.DEFAULT

    @model_validator(mode="after")
    def validate_selection(self) -> "ManagedSelection":
        if self.model is not None and self.provider is None:
            raise ValueError("a preferred model requires a preferred provider")
        return self


class ManagedConfig(Closed):
    """The whole managed profile. Unknown keys and unknown versions are rejected, not ignored."""

    schema_version: int
    installation_id: InstallationId
    locale: Literal["system", "en", "fr"] = "system"
    selection: ManagedSelection = ManagedSelection()
    providers: dict[Identifier, ManagedProvider] = Field(default_factory=dict)
    privacy: ManagedPrivacy = ManagedPrivacy()
    limits: ManagedLimits = ManagedLimits()
    client: ManagedClient | None = None

    @model_validator(mode="after")
    def validate_schema_version(self) -> "ManagedConfig":
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"unsupported managed schema version {self.schema_version}; "
                f"this build reads version {SCHEMA_VERSION}"
            )
        selected = self.selection.provider
        if selected is not None and not self.providers.get(selected, ManagedProvider()).enabled:
            raise ValueError(f"the preferred provider {selected} is not enabled")
        return self

    @property
    def enabled_providers(self) -> frozenset[str]:
        return frozenset(name for name, provider in self.providers.items() if provider.enabled)

    def to_toml_dict(self) -> dict[str, Any]:
        """Serialize without `None` values, which TOML cannot represent."""
        return _drop_none(self.model_dump(mode="json"))


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value
