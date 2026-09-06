from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from open_transcribe.server import create_app, create_server
from open_transcribe.service import TranscriptionService
from open_transcribe.settings import Settings


def test_health_and_readiness_do_not_expose_secrets(config_dir: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "bearer", "bearer_token": "top-secret"},
        groq={"api_key": "provider-secret"},
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready", "configured_providers": ["groq"]}
        assert "secret" not in ready.text


def test_mcp_route_requires_bearer_token(config_dir: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "bearer", "bearer_token": "top-secret"},
    )
    with TestClient(create_app(settings)) as client:
        response = client.post("/mcp", json={})
        assert response.status_code == 401
        assert response.json()["code"] == "AUTHENTICATION_FAILED"


@pytest.mark.asyncio
async def test_exact_mcp_tool_surface_and_structured_errors(config_dir: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "none"},
    )
    async with Client(create_server(settings)) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} == {
            "transcribe_audio",
            "get_transcript_chunk",
            "delete_transcript",
            "list_transcription_models",
            "estimate_transcription_cost",
        }
        schemas = " ".join(tool.model_dump_json() for tool in tools)
        assert "api_key" not in schemas
        assert "local_path" not in schemas
        assert "provider-native" not in schemas
        models = await client.call_tool("list_transcription_models", {})
        assert len(models.data) == 4
        estimate = await client.call_tool(
            "estimate_transcription_cost",
            {"duration_seconds": 1, "provider": "groq", "model": "missing"},
        )
        assert estimate.data["status"] == "error"
        assert estimate.data["error"]["code"] == "UNSUPPORTED_MODEL"
        deleted = await client.call_tool("delete_transcript", {"transcript_id": "tr_missing"})
        assert deleted.data["error"]["code"] == "RESULT_STORE_DISABLED"
        chunk = await client.call_tool("get_transcript_chunk", {"transcript_id": "tr_missing"})
        assert chunk.data["error"]["code"] == "RESULT_STORE_DISABLED"
        transcription = await client.call_tool(
            "transcribe_audio",
            {"request": {"source": {"url": "https://example.com/audio.mp3"}}},
        )
        assert transcription.data["error"]["code"] == "PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_unexpected_store_error_is_normalized_without_leaking_details(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={"auth_mode": "none"},
    )
    failure = "https://media.example/audio.mp3?signature=must-not-leak"
    monkeypatch.setattr(
        TranscriptionService,
        "get_chunk",
        AsyncMock(side_effect=RuntimeError(failure)),
    )
    async with Client(create_server(settings)) as client:
        result = await client.call_tool("get_transcript_chunk", {"transcript_id": "tr_missing"})
    assert result.data["error"]["code"] == "INTERNAL_ERROR"
    assert failure not in str(result.data)
