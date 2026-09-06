import pytest
from pydantic import ValidationError

from open_transcribe.domain.audio import TranscribeAudioRequest
from open_transcribe.settings import Settings


def test_request_rejects_model_without_explicit_provider() -> None:
    with pytest.raises(ValidationError, match="model requires"):
        TranscribeAudioRequest.model_validate(
            {"source": {"url": "https://example.com/audio.mp3"}, "model": "anything"}
        )


def test_request_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        TranscribeAudioRequest.model_validate(
            {"source": {"url": "https://example.com/audio.mp3"}, "api_key": "leak"}
        )


def test_request_rejects_oversized_phrase_hint() -> None:
    with pytest.raises(ValidationError, match="phrase hints"):
        TranscribeAudioRequest.model_validate(
            {
                "source": {"url": "https://example.com/audio.mp3"},
                "phrase_hints": ["x" * 51],
            }
        )


def test_production_requires_authentication() -> None:
    with pytest.raises(ValidationError, match="unauthenticated"):
        Settings(_env_file=None, environment="prod", security={"auth_mode": "none"})


def test_bearer_mode_requires_token() -> None:
    with pytest.raises(ValidationError, match="BEARER_TOKEN"):
        Settings(_env_file=None, environment="test", security={"auth_mode": "bearer"})
