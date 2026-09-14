"""Provider credentials in the session keyring.

There is no fallback. If Secret Service is unavailable, locked, or backed by a plaintext store,
setup fails with a recoverable error rather than writing a key somewhere weaker.
"""

import secrets
from typing import Protocol

from pydantic import SecretStr

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.schema import CREDENTIAL_NAMESPACE, CredentialRef

_LABEL = "OpenTranscribe"


def new_credential_ref(installation_id: str, provider: str, role: str) -> CredentialRef:
    """Mint a fresh reference so replacing a key never overwrites the working one in place."""
    return CredentialRef(
        service=CREDENTIAL_NAMESPACE,
        account=f"{installation_id}:{provider}:{role}:{secrets.token_hex(8)}",
    )


class CredentialStore(Protocol):
    """The only credential interface the rest of the desktop code may use."""

    def get(self, ref: CredentialRef) -> SecretStr | None: ...

    def put(self, ref: CredentialRef, secret: SecretStr) -> None: ...

    def delete(self, ref: CredentialRef) -> bool: ...


class SecretServiceCredentialStore:
    """A credential store bound to the freedesktop Secret Service backend specifically.

    The backend is instantiated directly rather than taken from keyring's priority chain, so an
    installed plaintext or in-memory backend can never satisfy a credential operation.
    """

    def __init__(self, backend: object | None = None) -> None:
        self._backend = backend if backend is not None else _secret_service_backend()

    def get(self, ref: CredentialRef) -> SecretStr | None:
        value = self._call("get_password", ref.service, ref.account)
        return SecretStr(value) if isinstance(value, str) and value else None

    def put(self, ref: CredentialRef, secret: SecretStr) -> None:
        value = secret.get_secret_value()
        if not value:
            raise DesktopError(
                DesktopErrorCode.CREDENTIAL_MISSING, "An empty credential cannot be stored."
            )
        self._call("set_password", ref.service, ref.account, value)

    def delete(self, ref: CredentialRef) -> bool:
        import keyring.errors

        try:
            self._call("delete_password", ref.service, ref.account)
        except DesktopError:
            raise
        except keyring.errors.PasswordDeleteError:
            return False
        return True

    def _call(self, name: str, *args: str) -> object:
        import keyring.errors

        try:
            return getattr(self._backend, name)(*args)
        except keyring.errors.KeyringLocked as exc:
            raise DesktopError(
                DesktopErrorCode.KEYRING_LOCKED,
                "Your session keyring is locked.",
                recovery="Unlock the keyring when your desktop asks, then try again.",
            ) from exc
        except keyring.errors.PasswordDeleteError:
            raise
        except keyring.errors.KeyringError as exc:
            raise DesktopError(
                DesktopErrorCode.KEYRING_UNAVAILABLE,
                "The session keyring could not be reached.",
                recovery=(
                    "Sign in to a normal graphical session with a running keyring service, "
                    "then open OpenTranscribe Setup again."
                ),
            ) from exc


def _secret_service_backend() -> object:
    try:
        from keyring.backends import SecretService
    except ImportError as exc:  # pragma: no cover - packaging guarantees the import
        raise DesktopError(
            DesktopErrorCode.KEYRING_UNAVAILABLE,
            "The Secret Service keyring backend is not installed.",
            recovery="Reinstall the OpenTranscribe Setup package.",
        ) from exc
    try:
        # keyring's own viability probe opens the session bus and the login collection. It is the
        # cheapest honest answer to "is there a real Secret Service here", and it stores nothing.
        SecretService.Keyring.priority  # noqa: B018
    except Exception as exc:
        raise DesktopError(
            DesktopErrorCode.KEYRING_UNAVAILABLE,
            "No Secret Service keyring is available in this session.",
            recovery=(
                "Sign in to a normal graphical session with a running keyring service "
                "(for example gnome-keyring), then open OpenTranscribe Setup again."
            ),
        ) from exc
    backend = SecretService.Keyring()
    backend.appid = _LABEL
    return backend


def keyring_available() -> bool:
    """Report whether a real Secret Service collection answers, without storing anything."""
    try:
        store = SecretServiceCredentialStore()
        store.get(CredentialRef(account="availability-probe"))
    except DesktopError:
        return False
    return True


class InMemoryCredentialStore:
    """A test double. It is never selected at runtime and never written to disk."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], str] = {}

    def get(self, ref: CredentialRef) -> SecretStr | None:
        value = self._items.get((ref.service, ref.account))
        return SecretStr(value) if value else None

    def put(self, ref: CredentialRef, secret: SecretStr) -> None:
        self._items[(ref.service, ref.account)] = secret.get_secret_value()

    def delete(self, ref: CredentialRef) -> bool:
        return self._items.pop((ref.service, ref.account), None) is not None
