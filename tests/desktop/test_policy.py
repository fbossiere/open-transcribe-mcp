"""SEC-06, SEC-07 and CFG-02: the engine enforces what the installation authorized."""

from unittest.mock import AsyncMock

import pytest

from open_transcribe.desktop.credentials import InMemoryCredentialStore
from open_transcribe.desktop.schema import ManagedConfig
from open_transcribe.domain.audio import (
    ProviderId,
    SourceDelivery,
    TranscribeAudioRequest,
)
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.policy import TranscriptionPolicy
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.routing.router import Router
from open_transcribe.settings import Settings
from open_transcribe.sources import resolver
from open_transcribe.sources.resolver import SourceBroker

SOURCE = {"type": "url", "url": "https://audio.example.com/sample.wav"}


@pytest.fixture
def offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source policy is exercised elsewhere; these tests are about the managed permission."""
    validated = resolver.ValidatedUrl(
        url=SOURCE["url"],
        scheme="https",
        host="audio.example.com",
        port=443,
        resolved_ips=("93.184.216.34",),
    )
    monkeypatch.setattr(resolver, "validate_source_url", AsyncMock(return_value=validated))


@pytest.fixture
def registry(settings: Settings) -> ProviderRegistry:
    return ProviderRegistry.from_settings(settings)


def route(registry: ProviderRegistry, settings: Settings, policy: TranscriptionPolicy, **kwargs):
    request = TranscribeAudioRequest(source=SOURCE, **kwargs)
    return Router(registry, settings, policy=policy).route(request)


def test_the_default_policy_leaves_the_existing_contract_alone(
    registry: ProviderRegistry, settings: Settings
) -> None:
    unrestricted = TranscriptionPolicy.unrestricted()
    assert unrestricted.permits_provider("anything")
    candidates = route(registry, settings, unrestricted)
    assert {candidate.model.provider for candidate in candidates} == {
        "microsoft",
        "elevenlabs",
        "groq",
    }


def test_a_disabled_provider_is_never_ranked(
    registry: ProviderRegistry, settings: Settings
) -> None:
    policy = TranscriptionPolicy(enabled_providers=frozenset({"groq"}))
    candidates = route(registry, settings, policy)
    assert {candidate.model.provider for candidate in candidates} == {"groq"}


def test_a_disabled_provider_cannot_be_requested_explicitly(
    registry: ProviderRegistry, settings: Settings
) -> None:
    policy = TranscriptionPolicy(enabled_providers=frozenset({"groq"}))
    with pytest.raises(OpenTranscribeError) as caught:
        route(registry, settings, policy, provider=ProviderId.ELEVENLABS)
    assert caught.value.response.code is ErrorCode.PROVIDER_NOT_ENABLED


def test_a_stored_key_alone_does_not_enable_a_provider(
    registry: ProviderRegistry, settings: Settings
) -> None:
    """Every provider in this fixture is configured; only the policy decides who may be used."""
    policy = TranscriptionPolicy(enabled_providers=frozenset())
    with pytest.raises(OpenTranscribeError) as caught:
        route(registry, settings, policy)
    assert caught.value.response.code is ErrorCode.PROVIDER_UNAVAILABLE


def test_fallback_stays_inside_the_selected_provider_when_disclosure_is_off(
    registry: ProviderRegistry, settings: Settings
) -> None:
    policy = TranscriptionPolicy(allow_cross_provider_fallback=False)
    candidates = route(
        registry, settings, policy, provider=ProviderId.GROQ, strict_capabilities=False
    )
    assert len(candidates) > 1
    assert {candidate.model.provider for candidate in candidates} == {"groq"}


def test_fallback_reaches_other_providers_when_disclosure_is_on(
    registry: ProviderRegistry, settings: Settings
) -> None:
    policy = TranscriptionPolicy(allow_cross_provider_fallback=True)
    candidates = route(registry, settings, policy, strict_capabilities=False)
    assert len({candidate.model.provider for candidate in candidates}) > 1


async def test_relay_is_refused_before_the_download(
    registry: ProviderRegistry, settings: Settings, offline_dns: None
) -> None:
    """A relay request fails before the source is contacted, so it costs neither bytes nor money."""
    policy = TranscriptionPolicy(allow_temporary_audio=False)
    broker = SourceBroker(settings, policy=policy, workspace=_never_called)
    model = registry.get_model("elevenlabs", "scribe-v2")
    with pytest.raises(OpenTranscribeError) as caught:
        async with broker.resolve(SOURCE["url"], SourceDelivery.PROXY, model):
            pass
    assert caught.value.response.code is ErrorCode.TEMPORARY_AUDIO_NOT_PERMITTED


async def test_passthrough_is_unaffected_by_the_relay_permission(
    registry: ProviderRegistry, settings: Settings, offline_dns: None
) -> None:
    policy = TranscriptionPolicy(allow_temporary_audio=False)
    broker = SourceBroker(settings, policy=policy, workspace=_never_called)
    model = registry.get_model("microsoft", "MAI-Transcribe-2")
    assert model.supports_url_input
    async with broker.resolve(SOURCE["url"], SourceDelivery.AUTO, model) as source:
        assert source.delivery is SourceDelivery.PASSTHROUGH
        assert source.local_path is None


def _never_called() -> str:
    raise AssertionError("no temporary file may be created for a refused relay")


def test_a_managed_profile_derives_its_policy_from_explicit_permissions() -> None:
    from open_transcribe.desktop.runtime import runtime_from_config

    config = ManagedConfig(
        schema_version=1,
        installation_id="0" * 32,
        providers={"groq": {"enabled": True}, "elevenlabs": {"enabled": False}},
    )
    runtime = runtime_from_config(config, credentials=InMemoryCredentialStore())
    assert runtime.policy.enabled_providers == frozenset({"groq"})
    assert runtime.policy.allow_cross_provider_fallback is False
    assert runtime.policy.allow_temporary_audio is False
