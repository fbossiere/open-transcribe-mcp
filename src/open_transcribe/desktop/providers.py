"""Normalized provider setup metadata and safe, non-transcribing credential checks.

The descriptors here are administrative. They describe what a setup form must collect and what
the engine can honestly verify. They are never exposed in an MCP schema, and a provider's native
response never reaches the user interface.
"""

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.schema import ManagedProvider

_CHECK_TIMEOUT_SECONDS = 15.0


class CheckOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_SUPPORTED = "not_supported"
    NOT_TESTED = "not_tested"


@dataclass(frozen=True, slots=True)
class CredentialCheck:
    """What a check established, phrased so it cannot be read as more than it is."""

    outcome: CheckOutcome
    message_key: str
    detail: str | None = None

    @property
    def passed(self) -> bool:
        return self.outcome is CheckOutcome.PASSED


@dataclass(frozen=True, slots=True)
class SetupField:
    """One field in the provider form, described for the UI without provider-native wording."""

    name: str
    label_key: str
    kind: str
    required: bool = True
    help_key: str | None = None
    placeholder: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderSetupDescriptor:
    provider_id: str
    display_name: str
    settings_key: str
    credential_roles: tuple[str, ...]
    fields: tuple[SetupField, ...]
    documentation_url: str
    account_url: str
    credential_check: str
    """The check this adapter can perform: `"api"` for a real one, `"none"` where none exists."""

    zero_retention_control: bool = False
    notes_key: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def supports_credential_check(self) -> bool:
        return self.credential_check != "none"


MICROSOFT = ProviderSetupDescriptor(
    provider_id="microsoft",
    display_name="Microsoft",
    settings_key="microsoft",
    credential_roles=("api_key",),
    fields=(
        SetupField(
            name="endpoint",
            label_key="provider.microsoft.endpoint",
            kind="https_url",
            help_key="provider.microsoft.endpoint.help",
        ),
        SetupField(name="api_key", label_key="provider.api_key", kind="secret"),
        SetupField(
            name="api_version",
            label_key="provider.microsoft.api_version",
            kind="text",
            required=False,
        ),
    ),
    documentation_url="https://learn.microsoft.com/azure/ai-services/speech-service/",
    account_url="https://portal.azure.com/",
    credential_check="none",
    notes_key="provider.microsoft.no_check",
)

ELEVENLABS = ProviderSetupDescriptor(
    provider_id="elevenlabs",
    display_name="ElevenLabs",
    settings_key="elevenlabs",
    credential_roles=("api_key",),
    fields=(SetupField(name="api_key", label_key="provider.api_key", kind="secret"),),
    documentation_url="https://elevenlabs.io/docs/capabilities/speech-to-text",
    account_url="https://elevenlabs.io/app/settings/api-keys",
    credential_check="api",
    zero_retention_control=True,
    extra={"check_path": "/v1/models", "auth_header": "xi-api-key", "base": "base_url"},
)

GROQ = ProviderSetupDescriptor(
    provider_id="groq",
    display_name="Groq",
    settings_key="groq",
    credential_roles=("api_key",),
    fields=(SetupField(name="api_key", label_key="provider.api_key", kind="secret"),),
    documentation_url="https://console.groq.com/docs/speech-to-text",
    account_url="https://console.groq.com/keys",
    credential_check="api",
    extra={"check_path": "/models", "auth_header": "authorization", "base": "base_url"},
)

DESCRIPTORS: tuple[ProviderSetupDescriptor, ...] = (MICROSOFT, ELEVENLABS, GROQ)
_BY_ID = {item.provider_id: item for item in DESCRIPTORS}


def descriptor_for(provider_id: str) -> ProviderSetupDescriptor:
    try:
        return _BY_ID[provider_id]
    except KeyError as exc:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            f"{provider_id} is not a provider this build supports.",
        ) from exc


def validate_credential_endpoint(url: str) -> str:
    """Check a destination that will carry a key. This is not the source-URL policy.

    Source URLs and credential-bearing provider endpoints are validated separately and on purpose:
    passing one has never been evidence for the other.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "A provider endpoint must use HTTPS before a key can be sent to it.",
        )
    if parts.username or parts.password:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "A provider endpoint must not embed credentials in its URL.",
        )
    host = (parts.hostname or "").rstrip(".").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "A provider endpoint must name a public host.",
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return url
    if not address.is_global:
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "A provider endpoint must not address a private network.",
        )
    return url


async def check_credential(
    descriptor: ProviderSetupDescriptor,
    managed: ManagedProvider,
    secret: SecretStr,
    *,
    base_url: str,
    client: httpx.AsyncClient | None = None,
) -> CredentialCheck:
    """Perform the provider's documented non-transcribing check, or report that there is none.

    A model catalog that answers proves the key authenticates. It does not prove entitlement to a
    model, that a transcription will succeed, or that future requests are free.
    """
    if not descriptor.supports_credential_check:
        return CredentialCheck(CheckOutcome.NOT_SUPPORTED, "check.not_supported")
    validate_credential_endpoint(base_url)
    path = str(descriptor.extra["check_path"])
    header = str(descriptor.extra["auth_header"])
    value = (
        f"Bearer {secret.get_secret_value()}"
        if header == "authorization"
        else secret.get_secret_value()
    )
    owned = client is None
    # Redirects are never followed: a key must not be forwarded to a host the user did not enter.
    active = client or httpx.AsyncClient(
        follow_redirects=False, timeout=_CHECK_TIMEOUT_SECONDS, trust_env=False
    )
    try:
        response = await active.get(
            base_url.rstrip("/") + path, headers={header: value, "accept": "application/json"}
        )
    except httpx.HTTPError:
        return CredentialCheck(CheckOutcome.FAILED, "check.unreachable")
    finally:
        if owned:
            await active.aclose()
    return _interpret(response.status_code)


def _interpret(status_code: int) -> CredentialCheck:
    """Map a status to a distinct, normalized message. No provider text is ever shown."""
    if 200 <= status_code < 300:
        return CredentialCheck(CheckOutcome.PASSED, "check.passed")
    if status_code in {301, 302, 303, 307, 308}:
        return CredentialCheck(CheckOutcome.FAILED, "check.redirected")
    if status_code in {401, 403}:
        return CredentialCheck(CheckOutcome.FAILED, "check.rejected")
    if status_code == 429:
        return CredentialCheck(CheckOutcome.FAILED, "check.rate_limited")
    if status_code == 402:
        return CredentialCheck(CheckOutcome.FAILED, "check.quota")
    return CredentialCheck(CheckOutcome.FAILED, "check.unavailable")
