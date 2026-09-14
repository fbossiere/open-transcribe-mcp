from enum import StrEnum


class DesktopErrorCode(StrEnum):
    """Normalized desktop failures. These never reach MCP clients."""

    CONFIG_MISSING = "CONFIG_MISSING"
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFIG_UNSUPPORTED_VERSION = "CONFIG_UNSUPPORTED_VERSION"
    CONFIG_UNSAFE_LOCATION = "CONFIG_UNSAFE_LOCATION"
    CONFIG_LOCKED = "CONFIG_LOCKED"
    KEYRING_UNAVAILABLE = "KEYRING_UNAVAILABLE"
    KEYRING_LOCKED = "KEYRING_LOCKED"
    CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
    ENGINE_MISSING = "ENGINE_MISSING"
    ENGINE_HANDSHAKE_FAILED = "ENGINE_HANDSHAKE_FAILED"
    CLIENT_UNSUPPORTED = "CLIENT_UNSUPPORTED"
    CLIENT_CONFLICT = "CLIENT_CONFLICT"
    CLIENT_REGISTRATION_FAILED = "CLIENT_REGISTRATION_FAILED"
    TEMP_AUDIO_UNAVAILABLE = "TEMP_AUDIO_UNAVAILABLE"
    PRIVILEGE_REFUSED = "PRIVILEGE_REFUSED"


class DesktopError(Exception):
    """A setup-time failure with a stable code and a message safe to show a user."""

    def __init__(
        self,
        code: DesktopErrorCode,
        message: str,
        *,
        recovery: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recovery = recovery
