"""Retry policy (SPEC 42) and provider error normalization (SPEC 41)."""

import httpx
import pytest
from tenacity import wait_none

from open_transcribe.domain.audio import ResolvedAudioSource, TranscribeAudioRequest
from open_transcribe.domain.capabilities import ModelDescriptor
from open_transcribe.domain.errors import ErrorCode, ProviderError
from open_transcribe.domain.transcript import CanonicalTranscript, CostEstimate
from open_transcribe.providers import base
from open_transcribe.providers.base import HttpProvider, safe_validate_transcript

PROVIDER_SECRET_BODY = {"detail": "https://bucket.example/a.mp3?X-Amz-Signature=must-not-leak"}


class ProbeProvider(HttpProvider):
    """Minimal adapter exercising only the shared HTTP retry and error mapping."""

    provider_id = "probe"
    configured = True

    def list_models(self) -> list[ModelDescriptor]:
        return []

    async def transcribe(
        self,
        request: TranscribeAudioRequest,
        source: ResolvedAudioSource,
        model: ModelDescriptor,
    ) -> CanonicalTranscript:
        raise NotImplementedError

    def estimate_cost(self, model: str, duration_seconds: float) -> CostEstimate:
        raise NotImplementedError


class Sender:
    """Replay prepared outcomes, repeating the last one, and count the attempts."""

    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def __call__(self) -> httpx.Response:
        self.calls += 1
        outcome = self.outcomes[min(self.calls, len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the retry timing out of the suite; the wait strategy is tested separately."""
    monkeypatch.setattr(base, "_BACKOFF", wait_none())


async def attempt(*outcomes: httpx.Response | Exception) -> tuple[Sender, ProviderError]:
    sender = Sender(*outcomes)
    with pytest.raises(ProviderError) as caught:
        await ProbeProvider(timeout_seconds=1)._request_with_retry(
            sender, provider="probe", model="probe-1"
        )
    return sender, caught.value


@pytest.mark.asyncio
async def test_server_error_is_retried_to_the_attempt_limit_then_normalized() -> None:
    sender, error = await attempt(httpx.Response(503))
    assert sender.calls == 3
    assert error.response.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert error.response.retryable
    assert error.response.details == {"reason": "provider_http_503"}


@pytest.mark.asyncio
async def test_rate_limit_is_retried_and_reported_as_rate_limited() -> None:
    sender, error = await attempt(httpx.Response(429))
    assert sender.calls == 3
    assert error.response.code == ErrorCode.RATE_LIMITED
    assert error.response.retryable, "SPEC 20.1 makes a rate limit fallback-eligible"
    assert error.response.details == {"reason": "provider_http_429"}


@pytest.mark.asyncio
async def test_timeout_is_retried_and_normalized_as_a_provider_timeout() -> None:
    sender, error = await attempt(httpx.ReadTimeout("timed out"))
    assert sender.calls == 3
    assert error.response.code == ErrorCode.PROVIDER_TIMEOUT
    assert error.response.retryable
    assert error.response.details == {"reason": "provider_timeout"}


@pytest.mark.asyncio
async def test_network_failure_is_retried_and_normalized() -> None:
    sender, error = await attempt(httpx.ConnectError("no route"))
    assert sender.calls == 3
    assert error.response.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert error.response.retryable
    assert error.response.details == {"reason": "provider_network_failure"}


@pytest.mark.asyncio
async def test_transient_failure_recovers_inside_the_attempt_limit() -> None:
    sender = Sender(httpx.Response(503), httpx.Response(200, json={"text": "ok"}))
    response, latency_ms = await ProbeProvider(timeout_seconds=1)._request_with_retry(
        sender, provider="probe", model="probe-1"
    )
    assert sender.calls == 2
    assert response.status_code == 200
    assert latency_ms >= 0


@pytest.mark.asyncio
async def test_authentication_failure_is_never_retried() -> None:
    sender, error = await attempt(httpx.Response(401, json=PROVIDER_SECRET_BODY))
    assert sender.calls == 1, "SPEC 42 forbids retrying an authentication failure"
    assert error.response.code == ErrorCode.PROVIDER_AUTHENTICATION_FAILED
    assert not error.response.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 404, 409, 413, 415, 422])
async def test_rejected_input_is_never_retried(status_code: int) -> None:
    sender, error = await attempt(httpx.Response(status_code, json=PROVIDER_SECRET_BODY))
    assert sender.calls == 1, "SPEC 42 forbids retrying a validation or unsupported-input error"
    assert error.response.code == ErrorCode.INVALID_AUDIO
    assert not error.response.retryable
    assert error.response.details == {"status_code": status_code}


@pytest.mark.asyncio
async def test_unmapped_client_error_is_normalized_without_retrying() -> None:
    sender, error = await attempt(httpx.Response(402, json=PROVIDER_SECRET_BODY))
    assert sender.calls == 1
    assert error.response.code == ErrorCode.PROVIDER_UNAVAILABLE
    assert not error.response.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 400, 402, 500])
async def test_normalized_errors_never_carry_the_provider_body(status_code: int) -> None:
    _, error = await attempt(httpx.Response(status_code, json=PROVIDER_SECRET_BODY))
    assert "must-not-leak" not in error.response.model_dump_json()


def test_status_mapping_agrees_with_the_retry_path_on_rate_limits() -> None:
    """The shared mapping helper must not disagree with the exhausted-retry outcome."""
    with pytest.raises(ProviderError) as caught:
        ProbeProvider._raise_for_status(httpx.Response(429), provider="probe", model="probe-1")
    assert caught.value.response.code == ErrorCode.RATE_LIMITED
    assert caught.value.response.retryable


def test_invalid_json_is_normalized() -> None:
    with pytest.raises(ProviderError) as caught:
        ProbeProvider.parse_json(
            httpx.Response(200, text="<html>not json</html>"), provider="probe", model="probe-1"
        )
    assert caught.value.response.code == ErrorCode.PROVIDER_RESPONSE_INVALID


def test_non_object_json_is_normalized() -> None:
    with pytest.raises(ProviderError) as caught:
        ProbeProvider.parse_json(
            httpx.Response(200, json=["unexpected"]), provider="probe", model="probe-1"
        )
    assert caught.value.response.code == ErrorCode.PROVIDER_RESPONSE_INVALID


def test_unnormalizable_transcript_is_rejected() -> None:
    with pytest.raises(ProviderError) as caught:
        safe_validate_transcript({"text": "missing every required field"}, provider="p", model="m")
    assert caught.value.response.code == ErrorCode.PROVIDER_RESPONSE_INVALID
    assert caught.value.response.provider == "p"
