"""USE and SEC coverage for the optional public sample: it is bounded, fixed, and honest."""

from pathlib import Path

import pytest

from open_transcribe.desktop import sample
from open_transcribe.domain.audio import RoutingPolicy
from open_transcribe.domain.errors import ErrorCode
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.settings import Settings

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "open-transcribe-bilingual.wav"


@pytest.fixture
def model(settings: Settings):
    return ProviderRegistry.from_settings(settings).get_model("groq", "whisper-large-v3-turbo")


def test_the_published_digest_matches_the_repository_fixture() -> None:
    assert sample.fixture_matches(FIXTURE)
    assert FIXTURE.stat().st_size == sample.SAMPLE_SIZE_BYTES


def test_the_sample_url_is_pinned_to_an_immutable_revision() -> None:
    assert sample.SAMPLE_REVISION in sample.SAMPLE_URL
    assert "/main/" not in sample.SAMPLE_URL
    assert sample.SAMPLE_URL.startswith("https://")


def test_the_sample_uses_the_ordinary_public_input(model) -> None:
    request = sample.sample_request(model)
    assert str(request.source.url) == sample.SAMPLE_URL
    assert request.source.type == "url"
    assert not hasattr(request, "local_path")


def test_the_sample_fixes_the_model_and_forbids_fallback(model) -> None:
    request = sample.sample_request(model)
    assert request.routing_policy is RoutingPolicy.FIXED
    assert request.allow_fallback is False
    assert request.strict_capabilities is True
    assert request.diarization is None
    assert request.timestamps is None


def test_a_capability_test_is_a_separate_explicit_request(model) -> None:
    extra = sample.capability_request(model)
    if extra is not None:
        assert extra.allow_fallback is False
        assert extra.diarization or extra.timestamps is not None


def test_an_unpriced_model_is_never_labelled_free(model) -> None:
    plan = sample.plan_sample(model.model_copy(update={"pricing": None}))
    assert plan.estimated_cost_usd is None
    assert plan.cost_is_known is False


def test_a_priced_model_carries_the_pricing_date(model) -> None:
    plan = sample.plan_sample(model)
    assert plan.cost_is_known
    assert plan.pricing_valid_from is not None
    assert plan.duration_seconds == pytest.approx(21.657)


def test_the_displayed_result_is_bounded_and_inert() -> None:
    result = sample.summarize(
        {
            "provider": "groq",
            "model": "whisper-large-v3-turbo",
            "language": "en",
            "text": "x" * (sample.MAX_DISPLAYED_CHARS + 500),
            "source_duration_ms": 21657,
            "warnings": ["w"] * 50,
        }
    )
    assert len(result.text_preview) == sample.MAX_DISPLAYED_CHARS
    assert result.truncated
    assert len(result.warnings) == 20


def test_each_failure_gets_a_distinct_message() -> None:
    keys = {
        sample.message_key_for(code.value)
        for code in (
            ErrorCode.PROVIDER_AUTHENTICATION_FAILED,
            ErrorCode.UNSUPPORTED_MODEL,
            ErrorCode.RATE_LIMITED,
            ErrorCode.SOURCE_UNAVAILABLE,
            ErrorCode.PROVIDER_UNAVAILABLE,
            ErrorCode.TEMPORARY_AUDIO_NOT_PERMITTED,
        )
    }
    assert len(keys) == 6
    assert sample.message_key_for("NOT_A_CODE") == "sample.error.unknown"
