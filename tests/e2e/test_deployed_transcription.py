"""End-to-end checks against a deployed OpenTranscribe instance.

Skipped unless a deployment URL is supplied. These tests call a real provider through the
deployment, so they cost money and are never part of an ordinary local or CI run:

    uv run pytest tests/e2e \
      --deployment-url "$(terraform output -raw mcp_endpoint)" \
      --bearer-token "$OT_SECURITY__BEARER_TOKEN"
"""

from typing import Any

import httpx
import pytest
from fastmcp import Client

from tests.e2e.conftest import Deployment, turn_coverage

pytestmark = pytest.mark.e2e_deployment

MAX_CHUNKS = 100


def tool_payload(result: Any, tool: str) -> dict[str, Any]:
    payload = result.data
    if not isinstance(payload, dict):
        pytest.fail(f"{tool} returned {type(payload).__name__}, expected a JSON object")
    if payload.get("status") == "error":
        error = payload["error"]
        pytest.fail(f"{tool} failed with {error['code']}: {error['message']}")
    return payload


async def read_stored_text(client: Client, transcript_id: str) -> str:
    chunks: list[str] = []
    cursor: str | None = None
    for _ in range(MAX_CHUNKS):
        result = await client.call_tool(
            "get_transcript_chunk",
            {"transcript_id": transcript_id, "cursor": cursor, "format": "text"},
        )
        chunk = tool_payload(result, "get_transcript_chunk")
        chunks.append(str(chunk["content"]))
        cursor = chunk["next_cursor"]
        if chunk["done"]:
            return "".join(chunks)
    pytest.fail(f"stored transcript was not exhausted after {MAX_CHUNKS} chunks")


async def configured_model(client: Client, deployment: Deployment) -> dict[str, Any]:
    """Ask the deployment which model to use, so the request matches what it can actually do."""
    result = await client.call_tool("list_transcription_models", {"configured_only": True})
    models = result.data
    if not models:
        pytest.fail("the deployment reports no configured transcription model")
    if deployment.provider == "auto" and deployment.model is None:
        return dict(models[0])
    selected = [
        model
        for model in models
        if deployment.provider in ("auto", model["provider"])
        and deployment.model in (None, model["model"])
    ]
    if not selected:
        keys = sorted(f"{model['provider']}/{model['model']}" for model in models)
        pytest.fail(
            f"requested {deployment.provider}/{deployment.model} is not configured; "
            f"the deployment offers {keys}"
        )
    return dict(selected[0])


async def transcript_text(client: Client, payload: dict[str, Any]) -> str:
    if payload["result_mode"] != "stored":
        return str(payload["text"])
    transcript_id = payload["transcript_id"]
    try:
        return await read_stored_text(client, transcript_id)
    finally:
        deletion = await client.call_tool("delete_transcript", {"transcript_id": transcript_id})
        assert tool_payload(deletion, "delete_transcript")["deleted"] is True


def test_health_endpoint_reports_ok(deployment: Deployment) -> None:
    response = httpx.get(deployment.url("healthz"), timeout=30)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_endpoint_lists_a_configured_provider(deployment: Deployment) -> None:
    response = httpx.get(deployment.url("readyz"), timeout=30)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["configured_providers"]


def test_mcp_endpoint_rejects_an_unauthenticated_call(deployment: Deployment) -> None:
    response = httpx.post(deployment.url("mcp"), json={}, timeout=30)
    assert response.status_code == 401


async def test_expected_tool_surface_is_reachable(authenticated_deployment: Deployment) -> None:
    async with authenticated_deployment.client() as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == {
        "transcribe_audio",
        "get_transcript_chunk",
        "delete_transcript",
        "list_transcription_models",
        "estimate_transcription_cost",
    }


async def test_transcribing_the_audio_returns_the_expected_words(
    authenticated_deployment: Deployment,
) -> None:
    deployment = authenticated_deployment
    async with deployment.client() as client:
        model = await configured_model(client, deployment)
        # Words are what this test verifies, so it requests the plainest transcript the selected
        # model supports rather than capabilities that vary by provider.
        request: dict[str, Any] = {
            "source": {"url": deployment.audio_url},
            "provider": model["provider"],
            "model": model["model"],
            "diarization": False,
            "timestamps": "none" if "none" in model["timestamp_modes"] else "segment",
            "transcript_style": ("clean" if "clean" in model["transcript_styles"] else "verbatim"),
        }
        result = await client.call_tool(
            "transcribe_audio", {"request": request}, timeout=deployment.timeout_seconds
        )
        payload = tool_payload(result, "transcribe_audio")
        assert payload["status"] == "completed"
        assert payload["provider"] == model["provider"]
        assert payload["model"]
        text = await transcript_text(client, payload)

    assert text.strip()
    coverage, missing, expected_count = turn_coverage(deployment.expected_transcript, text)
    # The transcript itself stays out of the failure message: a run against private audio would
    # otherwise print its content into the test log.
    assert coverage >= deployment.min_word_coverage, (
        f"the best-matching reference turn was only {coverage:.0%} covered out of "
        f"{expected_count} expected words (minimum {deployment.min_word_coverage:.0%}); "
        f"missing: {sorted(missing)}"
    )
