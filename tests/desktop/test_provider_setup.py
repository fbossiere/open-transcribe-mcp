"""SEC-05 and §7: provider setup metadata, and the endpoint policy that guards a key."""

import httpx
import pytest
import respx
from pydantic import SecretStr

from open_transcribe.desktop.errors import DesktopError
from open_transcribe.desktop.providers import (
    DESCRIPTORS,
    GROQ,
    MICROSOFT,
    CheckOutcome,
    check_credential,
    descriptor_for,
    validate_credential_endpoint,
)
from open_transcribe.desktop.schema import ManagedProvider


def test_every_descriptor_names_its_documentation_and_account_pages() -> None:
    for descriptor in DESCRIPTORS:
        assert descriptor.documentation_url.startswith("https://")
        assert descriptor.account_url.startswith("https://")
        assert descriptor.credential_roles


def test_a_descriptor_states_whether_a_check_exists_at_all() -> None:
    assert GROQ.supports_credential_check
    # Microsoft has no documented check that avoids transcribing, so it claims none.
    assert not MICROSOFT.supports_credential_check
    assert MICROSOFT.notes_key == "provider.microsoft.no_check"


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(DesktopError):
        descriptor_for("not-a-provider")


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "https://[::1]/v1",
        "https://localhost/v1",
        "https://user:pass@api.example.com/v1",
        "https:///v1",
    ],
)
def test_an_unsafe_endpoint_never_receives_a_key(url: str) -> None:
    with pytest.raises(DesktopError):
        validate_credential_endpoint(url)


def test_a_public_https_endpoint_is_accepted() -> None:
    assert validate_credential_endpoint("https://api.groq.com/openai/v1")


def test_endpoint_policy_is_separate_from_source_url_policy() -> None:
    """Passing one has never been evidence for the other; they are different functions."""
    from open_transcribe.security import ssrf

    assert validate_credential_endpoint is not ssrf.validate_source_url
    # The source policy allows plain HTTP when a deployment turns HTTPS off; the endpoint policy
    # that carries a credential has no such switch.
    with pytest.raises(DesktopError):
        validate_credential_endpoint("http://api.groq.com/openai/v1")


@respx.mock
async def test_a_successful_catalogue_response_means_the_key_authenticates() -> None:
    route = respx.get("https://api.groq.com/openai/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = await check_credential(
        GROQ, ManagedProvider(), SecretStr("k"), base_url="https://api.groq.com/openai/v1"
    )
    assert result.outcome is CheckOutcome.PASSED
    assert route.calls.last.request.headers["authorization"] == "Bearer k"


@respx.mock
@pytest.mark.parametrize(
    ("status", "expected_key"),
    [
        (401, "check.rejected"),
        (403, "check.rejected"),
        (402, "check.quota"),
        (429, "check.rate_limited"),
        (500, "check.unavailable"),
        (302, "check.redirected"),
    ],
)
async def test_each_failure_is_a_distinct_normalized_message(
    status: int, expected_key: str
) -> None:
    respx.get("https://api.groq.com/openai/v1/models").mock(
        return_value=httpx.Response(status, headers={"location": "https://evil.example.com"})
    )
    result = await check_credential(
        GROQ, ManagedProvider(), SecretStr("k"), base_url="https://api.groq.com/openai/v1"
    )
    assert result.outcome is CheckOutcome.FAILED
    assert result.message_key == expected_key


@respx.mock
async def test_a_redirect_never_forwards_the_key_to_another_host() -> None:
    first = respx.get("https://api.groq.com/openai/v1/models").mock(
        return_value=httpx.Response(307, headers={"location": "https://evil.example.com/models"})
    )
    stolen = respx.get("https://evil.example.com/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = await check_credential(
        GROQ, ManagedProvider(), SecretStr("k"), base_url="https://api.groq.com/openai/v1"
    )
    assert result.message_key == "check.redirected"
    assert first.called
    assert not stolen.called


async def test_a_provider_without_a_check_reports_not_supported() -> None:
    result = await check_credential(
        MICROSOFT,
        ManagedProvider(),
        SecretStr("k"),
        base_url="https://speech.example.com",
    )
    assert result.outcome is CheckOutcome.NOT_SUPPORTED
    assert result.message_key == "check.not_supported"


@respx.mock
async def test_an_unreachable_provider_is_a_failure_not_a_crash() -> None:
    respx.get("https://api.groq.com/openai/v1/models").mock(
        side_effect=httpx.ConnectError("no route")
    )
    result = await check_credential(
        GROQ, ManagedProvider(), SecretStr("k"), base_url="https://api.groq.com/openai/v1"
    )
    assert result.message_key == "check.unreachable"
