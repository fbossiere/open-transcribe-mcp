import base64
import hashlib
import hmac
import json
from typing import Any, cast

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError


class CursorCodec:
    def __init__(self, secret: str) -> None:
        self.secret = secret.encode()

    def encode(self, payload: dict[str, Any]) -> str:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(body + signature).decode().rstrip("=")

    def decode(self, token: str) -> dict[str, Any]:
        try:
            padding = "=" * (-len(token) % 4)
            raw = base64.urlsafe_b64decode(token + padding)
            body, signature = raw[:-32], raw[-32:]
            expected = hmac.new(self.secret, body, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                self._invalid("invalid signature")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                self._invalid("invalid payload")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OpenTranscribeError(
                ErrorCode.RESULT_NOT_FOUND, "The transcript cursor is invalid."
            ) from exc
        else:
            return cast(dict[str, Any], payload)

    @staticmethod
    def _invalid(message: str) -> None:
        raise TypeError(message)
