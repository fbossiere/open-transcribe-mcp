from open_transcribe.domain.audio import ResolvedTranscribeRequest
from open_transcribe.providers.elevenlabs.adapter import ElevenLabsProvider
from open_transcribe.providers.groq.adapter import GroqProvider
from open_transcribe.providers.microsoft.adapter import MicrosoftProvider
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.settings import Settings


def request(**overrides: object) -> ResolvedTranscribeRequest:
    data: dict[str, object] = {
        "source": {"url": "https://example.com/audio.mp3"},
        "diarization": True,
        "transcript_style": "verbatim",
        "timestamps": "word",
    }
    data.update(overrides)
    return ResolvedTranscribeRequest.model_validate(data)


def providers(settings: Settings) -> tuple[MicrosoftProvider, ElevenLabsProvider, GroqProvider]:
    registry = ProviderRegistry.from_settings(settings)
    return (
        registry.get_provider("microsoft"),  # type: ignore[return-value]
        registry.get_provider("elevenlabs"),  # type: ignore[return-value]
        registry.get_provider("groq"),  # type: ignore[return-value]
    )


def test_microsoft_normalization(settings: Settings) -> None:
    microsoft, _, _ = providers(settings)
    model = microsoft.list_models()[0]
    result = microsoft.normalize(
        {
            "durationMilliseconds": 1200,
            "combinedPhrases": [{"text": "Bonjour world."}],
            "phrases": [
                {
                    "offsetMilliseconds": 0,
                    "durationMilliseconds": 1200,
                    "text": "Bonjour world.",
                    "locale": "fr-FR",
                    "speaker": 2,
                    "words": [
                        {"text": "Bonjour", "offsetMilliseconds": 0, "durationMilliseconds": 600}
                    ],
                }
            ],
        },
        request=request(),
        model=model,
        latency_ms=5,
        request_id="ms-id",
    )
    assert result.text == "Bonjour world."
    assert result.detected_languages == ["fr"]
    assert result.segments
    assert result.segments[0].speaker == "SPEAKER_01"
    assert result.segments[0].words
    assert result.segments[0].words[0].end_ms == 600


def test_elevenlabs_normalization(settings: Settings) -> None:
    _, eleven, _ = providers(settings)
    model = eleven.list_models()[0]
    result = eleven.normalize(
        {
            "language_code": "en",
            "text": "Hello there",
            "words": [
                {"type": "word", "text": "Hello", "start": 0.0, "end": 0.5, "speaker_id": "a"},
                {"type": "spacing", "text": " ", "start": 0.5, "end": 0.6, "speaker_id": "a"},
                {"type": "word", "text": "there", "start": 0.6, "end": 1.0, "speaker_id": "b"},
            ],
        },
        request=request(),
        model=model,
        latency_ms=5,
        request_id="eleven-id",
    )
    assert result.text == "Hello there"
    assert result.segments
    assert len(result.segments) == 2
    assert result.segments[1].speaker == "SPEAKER_02"


def test_groq_normalization(settings: Settings) -> None:
    _, _, groq = providers(settings)
    model = groq.list_models()[0]
    result = groq.normalize(
        {
            "language": "english",
            "duration": 1.0,
            "text": "Hello world",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hello world"}],
            "words": [
                {"start": 0.0, "end": 0.5, "word": "Hello"},
                {"start": 0.5, "end": 1.0, "word": "world"},
            ],
        },
        request=request(diarization=False),
        model=model,
        latency_ms=5,
        request_id="groq-id",
    )
    assert result.text == "Hello world"
    assert result.source_duration_ms == 1000
    assert result.segments
    assert len(result.segments[0].words or []) == 2
