import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

DEFAULT_AUDIO_URL = (
    "https://raw.githubusercontent.com/fbossiere/open-transcribe-mcp/main/"
    "tests/fixtures/open-transcribe-bilingual.wav"
)
DEFAULT_EXPECTED_TRANSCRIPT = Path(__file__).parents[1] / "fixtures" / "reference-transcript.txt"
DEFAULT_MIN_WORD_COVERAGE = 0.8
DEFAULT_TIMEOUT_SECONDS = 600.0
SERVICE_PATHS = ("mcp", "healthz", "readyz")
SPEAKER_PREFIX = re.compile(r"^SPEAKER_\d+\s*\[[^\]]*\]:", re.MULTILINE)
STREAM_MATCH_MIN_LENGTH = 6


@dataclass(frozen=True)
class Deployment:
    """A deployed OpenTranscribe instance and the audio to exercise it with."""

    base_url: str
    bearer_token: str | None
    audio_url: str
    expected_transcript: str
    min_word_coverage: float
    provider: str
    model: str | None
    timeout_seconds: float

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path}"

    def client(self) -> Client:
        headers = {"Authorization": f"Bearer {self.bearer_token}"} if self.bearer_token else {}
        return Client(
            StreamableHttpTransport(self.url("mcp"), headers=headers),
            timeout=self.timeout_seconds,
        )


def _option(request: pytest.FixtureRequest, name: str, env: str) -> str | None:
    value = request.config.getoption(name)
    return str(value) if value is not None else os.environ.get(env)


def _base_url(raw: str) -> str:
    """Accept any of the Terraform endpoint outputs, which differ only by their path."""
    trimmed = raw.strip().rstrip("/")
    for path in SERVICE_PATHS:
        if trimmed.endswith(f"/{path}"):
            return trimmed[: -len(path) - 1]
    return trimmed


def _expected_transcript(value: str | None) -> str:
    if value is None:
        return DEFAULT_EXPECTED_TRANSCRIPT.read_text(encoding="utf-8")
    candidate = Path(value)
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return value


@pytest.fixture(scope="session")
def deployment(request: pytest.FixtureRequest) -> Deployment:
    raw_url = _option(request, "--deployment-url", "OT_E2E_DEPLOYMENT_URL")
    if not raw_url:
        pytest.skip("no deployment URL: pass --deployment-url or set OT_E2E_DEPLOYMENT_URL")
    coverage = _option(request, "--min-word-coverage", "OT_E2E_MIN_WORD_COVERAGE")
    timeout = _option(request, "--e2e-timeout", "OT_E2E_TIMEOUT_SECONDS")
    return Deployment(
        base_url=_base_url(raw_url),
        bearer_token=_option(request, "--bearer-token", "OT_E2E_BEARER_TOKEN"),
        audio_url=_option(request, "--audio-url", "OT_E2E_AUDIO_URL") or DEFAULT_AUDIO_URL,
        expected_transcript=_expected_transcript(
            _option(request, "--expected-transcript", "OT_E2E_EXPECTED_TRANSCRIPT")
        ),
        min_word_coverage=float(coverage) if coverage else DEFAULT_MIN_WORD_COVERAGE,
        provider=_option(request, "--transcribe-provider", "OT_E2E_PROVIDER") or "auto",
        model=_option(request, "--transcribe-model", "OT_E2E_MODEL"),
        timeout_seconds=float(timeout) if timeout else DEFAULT_TIMEOUT_SECONDS,
    )


@pytest.fixture(scope="session")
def authenticated_deployment(deployment: Deployment) -> Deployment:
    if not deployment.bearer_token:
        pytest.skip("no bearer token: pass --bearer-token or set OT_E2E_BEARER_TOKEN")
    return deployment


def words(text: str) -> list[str]:
    """Fold a transcript to bare ASCII words so provider styling cannot fail the comparison."""
    without_speakers = SPEAKER_PREFIX.sub(" ", text)
    decomposed = unicodedata.normalize("NFKD", without_speakers.casefold())
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.findall(r"[a-z0-9]+", unaccented)


def turn_coverage(expected: str, actual: str) -> tuple[float, set[str], int]:
    """Score the reference turn the transcript reproduces best.

    The comparison is per line rather than over the whole reference because a model that detects
    a single language transcribes only its own half of the bilingual fixture and silently drops
    the rest, which says nothing about the words it did return. Returns the best turn's coverage,
    the expected words it still misses, and how many words that turn expected.
    """
    actual_words = words(actual)
    actual_set = set(actual_words)
    # Providers split or join compounds such as "OpenTranscribe" unpredictably, so a long word
    # also counts as spoken when it appears in the transcript's concatenated word stream.
    actual_stream = "".join(actual_words)
    best = (0.0, set[str](), 0)
    for line in expected.splitlines():
        expected_words = {word for word in words(line) if len(word) >= 3}
        if not expected_words:
            continue
        missing = {
            word
            for word in expected_words
            if word not in actual_set
            and not (len(word) >= STREAM_MATCH_MIN_LENGTH and word in actual_stream)
        }
        score = 1 - len(missing) / len(expected_words)
        if score > best[0] or best[2] == 0:
            best = (score, missing, len(expected_words))
    if best[2] == 0:
        raise ValueError("the expected transcript contains no comparable words")
    return best
