from typing import Any, Literal

import structlog
import uvicorn
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from open_transcribe.domain.audio import TranscribeAudioRequest
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.domain.transcript import ToolErrorResult
from open_transcribe.observability.logging import configure_logging
from open_transcribe.providers.registry import ProviderRegistry
from open_transcribe.result_store.factory import create_result_store
from open_transcribe.routing.router import Router
from open_transcribe.security.auth import BearerAuthMiddleware
from open_transcribe.service import TranscriptionService
from open_transcribe.settings import Settings, get_settings
from open_transcribe.sources.resolver import SourceBroker


def create_service(settings: Settings) -> TranscriptionService:
    registry = ProviderRegistry.from_settings(settings)
    return TranscriptionService(
        settings,
        registry,
        Router(registry, settings),
        SourceBroker(settings),
        create_result_store(settings),
    )


def create_server(config: Settings) -> FastMCP:
    configure_logging()
    service = create_service(config)
    mcp = FastMCP("OpenTranscribe")
    logger = structlog.get_logger()

    def failure(exc: OpenTranscribeError) -> ToolErrorResult:
        logger.warning(
            "tool_failed",
            code=exc.response.code.value,
            provider=exc.response.provider,
            model=exc.response.model,
            retryable=exc.response.retryable,
        )
        return ToolErrorResult(error=exc.response)

    def internal_failure(tool: str) -> ToolErrorResult:
        # Exception strings and tracebacks may contain signed URLs or provider data.
        logger.error("unexpected_tool_failure", tool=tool)
        return failure(
            OpenTranscribeError(ErrorCode.INTERNAL_ERROR, "An unexpected internal error occurred.")
        )

    @mcp.tool
    async def transcribe_audio(
        request: TranscribeAudioRequest,
    ) -> dict[str, Any]:
        """Transcribe an authorized HTTPS audio URL into the canonical schema."""
        try:
            return (await service.transcribe(request)).model_dump(mode="json")
        except OpenTranscribeError as exc:
            return failure(exc).model_dump(mode="json")
        except Exception:
            return internal_failure("transcribe_audio").model_dump(mode="json")

    @mcp.tool
    async def get_transcript_chunk(
        transcript_id: str,
        cursor: str | None = None,
        max_chars: int = 30000,
        format: Literal["text", "segments"] = "text",
    ) -> dict[str, Any]:
        """Read a bounded chunk from an explicitly enabled temporary result store."""
        try:
            result = await service.get_chunk(transcript_id, cursor, max_chars, format)
            return result.model_dump(mode="json")
        except OpenTranscribeError as exc:
            return failure(exc).model_dump(mode="json")
        except Exception:
            return internal_failure("get_transcript_chunk").model_dump(mode="json")

    @mcp.tool
    async def delete_transcript(transcript_id: str) -> dict[str, Any]:
        """Idempotently delete a temporarily stored transcript."""
        try:
            return (await service.delete(transcript_id)).model_dump(mode="json")
        except OpenTranscribeError as exc:
            return failure(exc).model_dump(mode="json")
        except Exception:
            return internal_failure("delete_transcript").model_dump(mode="json")

    @mcp.tool
    def list_transcription_models(configured_only: bool = False) -> list[dict[str, Any]]:
        """List model lifecycle, configuration state, limits, and capabilities."""
        return [
            item.model_dump(mode="json")
            for item in service.list_models(configured_only=configured_only)
        ]

    @mcp.tool
    def estimate_transcription_cost(
        duration_seconds: float, provider: str, model: str
    ) -> dict[str, Any]:
        """Return a non-contractual cost estimate from versioned pricing metadata."""
        try:
            return service.estimate_cost(duration_seconds, provider, model).model_dump(mode="json")
        except OpenTranscribeError as exc:
            return failure(exc).model_dump(mode="json")
        except Exception:
            return internal_failure("estimate_transcription_cost").model_dump(mode="json")

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @mcp.custom_route("/readyz", methods=["GET"])
    async def readyz(_: Request) -> JSONResponse:
        providers = sorted(
            provider.provider_id
            for provider in service.registry.providers.values()
            if provider.configured
        )
        status_code = 200 if providers else 503
        return JSONResponse(
            {"status": "ready" if providers else "not_ready", "configured_providers": providers},
            status_code=status_code,
        )

    return mcp


def create_app(settings: Settings | None = None) -> Any:
    config = settings or get_settings()
    mcp = create_server(config)
    token = (
        config.security.bearer_token.get_secret_value() if config.security.bearer_token else None
    )
    middleware = [
        Middleware(
            BearerAuthMiddleware,
            token=token,
            enabled=config.security.auth_mode == "bearer",
        )
    ]
    return mcp.http_app(path="/mcp", stateless_http=True, middleware=middleware)


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, workers=1)


if __name__ == "__main__":
    main()
