import hmac
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp.server.auth import AccessToken, JWTVerifier
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


class ClaimRestrictedJWTVerifier(JWTVerifier):
    """Require a bounded user entitlement in addition to JWT issuer, audience and scope."""

    def __init__(self, *, claim_path: str, claim_value: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.claim_path = claim_path.split(".")
        self.claim_value = claim_value

    async def verify_token(self, token: str) -> AccessToken | None:
        access = await super().verify_token(token)
        if access is None:
            return None
        claims = access.claims
        now = time.time()
        expiry = claims.get("exp")
        not_before = claims.get("nbf")
        if not isinstance(expiry, (int, float)) or expiry <= now:
            return None
        if not_before is not None and (
            not isinstance(not_before, (int, float)) or not_before > now
        ):
            return None
        value: Any = claims
        for component in self.claim_path:
            if not isinstance(value, dict):
                return None
            value = value.get(component)
        if isinstance(value, list):
            return access if self.claim_value in value else None
        return access if value == self.claim_value else None
