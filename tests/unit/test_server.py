import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp import Client
from fastmcp.server.auth import AccessToken, JWTVerifier
from joserfc import jwk, jwt
from starlette.testclient import TestClient

from open_transcribe.security.auth import ClaimRestrictedJWTVerifier
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


def test_oidc_discovery_and_unauthenticated_rejection(config_dir: Path) -> None:
    issuer = "https://keycloak.example/realms/transcribe"
    settings = Settings(
        _env_file=None,
        environment="test",
        config_dir=config_dir,
        security={
            "auth_mode": "oidc",
            "oidc_issuer_url": issuer,
            "oidc_jwks_url": f"{issuer}/protocol/openid-connect/certs",
            "oidc_public_base_url": "https://transcribe.example",
            "oidc_required_claim_value": "transcribe-user",
        },
    )
    with TestClient(create_app(settings)) as client:
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
        assert metadata.status_code == 200
        assert metadata.json()["resource"] == "https://transcribe.example/mcp"
        assert metadata.json()["authorization_servers"] == [issuer]
        assert metadata.json()["scopes_supported"] == ["mcp:tools"]
        rejected = client.post("/mcp", json={})
        assert rejected.status_code == 401
        assert "resource_metadata=" in rejected.headers["www-authenticate"]
        assert (
            client.post("/mcp", json={}, headers={"Authorization": "Bearer bad"}).status_code == 401
        )
        assert client.get("/healthz").status_code == 200


@pytest.mark.asyncio
async def test_oidc_requires_unexpired_token_and_entitlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims: dict[str, object] = {
        "exp": time.time() + 60,
        "realm_access": {"roles": ["transcribe-user"]},
    }

    async def verified_token(_: JWTVerifier, token: str) -> AccessToken:
        return AccessToken(token=token, client_id="test", scopes=["mcp:tools"], claims=claims)

    monkeypatch.setattr(JWTVerifier, "verify_token", verified_token)
    verifier = ClaimRestrictedJWTVerifier(
        public_key="test-key",
        algorithm="HS256",
        claim_path="realm_access.roles",
        claim_value="transcribe-user",
    )
    assert await verifier.verify_token("signed") is not None
    claims["realm_access"] = {"roles": ["other-role"]}
    assert await verifier.verify_token("signed") is None
    claims["realm_access"] = {"roles": ["transcribe-user"]}
    claims["exp"] = time.time() - 1
    assert await verifier.verify_token("signed") is None
    claims.pop("exp")
    assert await verifier.verify_token("signed") is None
    claims["exp"] = time.time() + 60
    claims["nbf"] = time.time() + 60
    assert await verifier.verify_token("signed") is None


@pytest.mark.asyncio
async def test_oidc_verifies_signature_issuer_audience_scope_and_role() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    verifier = ClaimRestrictedJWTVerifier(
        public_key=public_key,
        issuer="https://id.example/realms/test",
        audience="https://transcribe.example/mcp",
        algorithm="RS256",
        required_scopes=["mcp:tools"],
        claim_path="realm_access.roles",
        claim_value="transcribe-user",
    )
    claims = {
        "iss": "https://id.example/realms/test",
        "aud": "https://transcribe.example/mcp",
        "exp": int(time.time()) + 60,
        "scope": "mcp:tools",
        "realm_access": {"roles": ["transcribe-user"]},
    }

    def signed_token(values: dict[str, object], key: rsa.RSAPrivateKey = private_key) -> str:
        return jwt.encode({"alg": "RS256"}, values, jwk.RSAKey.import_key(key))

    assert await verifier.verify_token(signed_token(claims)) is not None
    for override in (
        {"iss": "https://other.example/realms/test"},
        {"aud": "https://other.example/mcp"},
        {"scope": "openid"},
        {"realm_access": {"roles": ["other-role"]}},
    ):
        assert await verifier.verify_token(signed_token({**claims, **override})) is None
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert await verifier.verify_token(signed_token(claims, other_key)) is None


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
