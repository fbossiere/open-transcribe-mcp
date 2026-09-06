import hmac
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

ASGIApp = Callable[
    [dict[str, Any], Callable[..., Awaitable[dict[str, Any]]], Callable[..., Awaitable[None]]],
    Awaitable[None],
]


class BearerAuthMiddleware:
    """Protect MCP routes with a single deployment-scoped opaque bearer token."""

    def __init__(self, app: ASGIApp, *, token: str | None, enabled: bool) -> None:
        self.app = app
        self.token = token
        self.enabled = enabled

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        if (
            not self.enabled
            or scope.get("type") != "http"
            or not scope.get("path", "").startswith("/mcp")
        ):
            await self.app(scope, receive, send)
            return
        header = Headers(scope=scope).get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else ""
        if self.token is None or not hmac.compare_digest(supplied, self.token):
            response = JSONResponse(
                {"code": "AUTHENTICATION_FAILED", "message": "A valid bearer token is required."},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
