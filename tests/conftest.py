from pathlib import Path

import pytest

from open_transcribe.settings import Settings


def pytest_addoption(parser: pytest.Parser) -> None:
    """Point the end-to-end suite at a deployed instance; each option has an OT_E2E_* fallback."""
    group = parser.getgroup("open-transcribe end-to-end")
    group.addoption(
        "--deployment-url",
        default=None,
        help="Deployed instance URL, in its base, /mcp, /healthz or /readyz form "
        "(terraform output -raw mcp_endpoint). Env: OT_E2E_DEPLOYMENT_URL.",
    )
    group.addoption(
        "--bearer-token",
        default=None,
        help="MCP bearer token of the deployment. Prefer the OT_E2E_BEARER_TOKEN environment "
        "variable, which keeps the secret out of the process list and shell history.",
    )
    group.addoption(
        "--audio-url",
        default=None,
        help="HTTPS URL of the audio to transcribe, defaulting to the repository's synthetic "
        "bilingual fixture. Env: OT_E2E_AUDIO_URL.",
    )
    group.addoption(
        "--expected-transcript",
        default=None,
        help="Reference transcript for that audio, as a file path or literal text, defaulting to "
        "tests/fixtures/reference-transcript.txt. Env: OT_E2E_EXPECTED_TRANSCRIPT.",
    )
    group.addoption(
        "--min-word-coverage",
        default=None,
        help="Share of the best-matching reference turn the transcript must reproduce, "
        "default 0.8. Env: OT_E2E_MIN_WORD_COVERAGE.",
    )
    group.addoption(
        "--transcribe-provider",
        default=None,
        help="Provider to request, default 'auto'. Env: OT_E2E_PROVIDER.",
    )
    group.addoption(
        "--transcribe-model",
        default=None,
        help="Model to request, only with an explicit provider. Env: OT_E2E_MODEL.",
    )
    group.addoption(
        "--e2e-timeout",
        default=None,
        help="Transcription timeout in seconds, default 600. Env: OT_E2E_TIMEOUT_SECONDS.",
    )


@pytest.fixture
def config_dir() -> Path:
    return Path(__file__).parents[1] / "config"


@pytest.fixture
def settings(config_dir: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "none"},
        microsoft={
            "endpoint": "https://speech.example.com",
            "api_key": "microsoft-secret",
        },
        elevenlabs={"api_key": "eleven-secret"},
        groq={"api_key": "groq-secret"},
        result_store={
            "backend": "memory",
            "cursor_secret": "cursor-secret-with-sufficient-entropy",
            "ttl_seconds": 3600,
        },
    )
