"""Opt-in Groq verification: one synthetic audio upload, shared by all transcript checks.

    uv run pytest tests/integration --live-groq --live-env-file .env.local -q

The MCP server runs in-process; no listening port or deployed service is needed.
Ordinary pytest runs never read the credential file or call Groq.
"""

import asyncio
import re
import secrets
from pathlib import Path
from typing import Any

import pytest
import respx
from fastmcp import Client
from pydantic import ValidationError
from starlette.testclient import TestClient

from open_transcribe.domain.transcript import InlineTranscriptionResult
from open_transcribe.server import create_app, create_server
from open_transcribe.settings import Settings

pytestmark = pytest.mark.integration_groq

FIXTURE_URL = (
    "https://raw.githubusercontent.com/fbossiere/open-transcribe-mcp/main/"
    "tests/fixtures/open-transcribe-bilingual.wav"
)
REFERENCE = Path(__file__).parents[1] / "fixtures" / "reference-transcript.txt"


def require(condition: bool, message: str) -> None:
    """Report only the failed invariant, never the provider payload or credentials."""
    __tracebackhide__ = True
    if not condition:
        pytest.fail(message, pytrace=False)


@pytest.fixture(scope="module")
def live_settings(request: pytest.FixtureRequest) -> Settings:
    __tracebackhide__ = True
    if not request.config.getoption("--live-groq"):
        pytest.skip("real Groq calls require --live-groq")
    env_file = Path(request.config.getoption("--live-env-file"))
    require(env_file.is_file(), "The live credential file does not exist.")
    try:
        settings = Settings(
            _env_file=env_file,
            _env_ignore_empty=True,
            environment="test",
            host="127.0.0.1",
            security={
                "auth_mode": "bearer",
                "bearer_token": secrets.token_urlsafe(32),
                "require_https_sources": True,
                "allow_private_urls": False,
                "allowed_source_hosts": ["raw.githubusercontent.com"],
            },
            result_store={"backend": "disabled"},
            provider_timeout_seconds=90,
            source_download_timeout_seconds=30,
        )
    except ValidationError as exc:
        fields = sorted(".".join(map(str, error["loc"])) for error in exc.errors())
        pytest.fail(f"Invalid live settings in fields: {', '.join(fields)}", pytrace=False)
    require(settings.groq.api_key is not None, "OT_GROQ__API_KEY is missing or empty.")
    return settings


async def call(settings: Settings, tool: str, arguments: dict[str, Any]) -> Any:
    async with Client(create_server(settings), timeout=180) as client:
        return (await client.call_tool(tool, arguments)).data


@pytest.fixture(scope="module")
def live_model(request: pytest.FixtureRequest, live_settings: Settings) -> str:
    return str(request.config.getoption("--groq-model"))


@pytest.fixture(scope="module")
def transcript(live_settings: Settings, live_model: str) -> InlineTranscriptionResult:
    __tracebackhide__ = True
    payload = asyncio.run(
        call(
            live_settings,
            "transcribe_audio",
            {
                "request": {
                    "source": {"type": "url", "url": FIXTURE_URL},
                    "provider": "groq",
                    "model": live_model,
                    "language": "en",
                    "diarization": False,
                    "timestamps": "segment",
                    "transcript_style": "verbatim",
                    "allow_fallback": False,
                    "source_delivery": "proxy",
                    "result_mode": "inline",
                }
            },
        )
    )
    require(isinstance(payload, dict), "MCP did not return a JSON object.")
    if payload.get("status") == "error":
        code = payload.get("error", {}).get("code", "UNKNOWN")
        pytest.fail(f"Live Groq transcription failed: {code}", pytrace=False)
    try:
        return InlineTranscriptionResult.model_validate(payload)
    except ValidationError:
        pytest.fail("Groq result does not satisfy the canonical transcript schema.", pytrace=False)


def test_local_health_readiness_and_authentication(live_settings: Settings) -> None:
    with TestClient(create_app(live_settings)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert "groq" in ready.json()["configured_providers"]
        assert client.post("/mcp", json={}).status_code == 401


def test_requested_groq_model_is_available(live_settings: Settings, live_model: str) -> None:
    models = asyncio.run(
        call(live_settings, "list_transcription_models", {"configured_only": True})
    )
    selected = [m for m in models if m["provider"] == "groq" and m["model"] == live_model]
    assert len(selected) == 1
    assert selected[0]["supports_diarization"] is False
    assert "segment" in selected[0]["timestamp_modes"]


def test_groq_rejects_diarization_without_network(live_settings: Settings, live_model: str) -> None:
    with respx.mock(assert_all_mocked=True) as network:
        payload = asyncio.run(
            call(
                live_settings,
                "transcribe_audio",
                {
                    "request": {
                        "source": {"url": FIXTURE_URL},
                        "provider": "groq",
                        "model": live_model,
                        "diarization": True,
                        "allow_fallback": False,
                    }
                },
            )
        )
        assert payload["error"]["code"] == "UNSUPPORTED_CAPABILITY"
        assert not network.calls


def test_real_transcript_has_the_requested_contract(
    transcript: InlineTranscriptionResult, live_model: str
) -> None:
    require(transcript.provider == "groq", "The result came from another provider.")
    require(transcript.model == live_model, "The result came from another model.")
    require(not transcript.metadata.fallback_used, "Unexpected provider fallback.")
    require(not transcript.metadata.diarization, "Unexpected diarization.")
    require(transcript.metadata.timestamps == "segment", "Segment timestamps were not applied.")
    require(transcript.metadata.transcript_style == "verbatim", "Verbatim mode was not applied.")
    require(all(s.speaker is None for s in transcript.segments or []), "Unexpected speaker labels.")


def test_real_transcript_contains_the_english_reference(
    transcript: InlineTranscriptionResult,
) -> None:
    # Groq does not promise code switching. Verify both English turns, not bilingual fidelity.
    reference = " ".join(
        line.split(":", 1)[1]
        for line in REFERENCE.read_text(encoding="utf-8").splitlines()
        if "[en]:" in line
    )
    expected = set(re.findall(r"[a-z]+", reference.lower()))
    actual = set(re.findall(r"[a-z]+", (transcript.text or "").lower()))
    coverage = len(expected & actual) / len(expected)
    require(coverage >= 0.8, f"English reference word coverage is {coverage:.0%}; expected 80%.")


def test_real_transcript_has_usable_segment_timestamps(
    transcript: InlineTranscriptionResult,
) -> None:
    require(bool(transcript.segments), "No transcript segments were returned.")
    require(bool(transcript.source_duration_ms), "Audio duration was not reported.")
    previous_start = 0
    for segment in transcript.segments or []:
        require(segment.start_ms is not None and segment.end_ms is not None, "Missing timestamps.")
        start, end = segment.start_ms or 0, segment.end_ms or 0
        require(0 <= previous_start <= start <= end, "Invalid or unordered segment timestamps.")
        previous_start = start
