"""SEC-01 and SEC-02: no weaker credential path, and no ambient configuration."""

from pathlib import Path

import pytest
from pydantic import SecretStr

from open_transcribe.desktop.credentials import (
    InMemoryCredentialStore,
    SecretServiceCredentialStore,
    keyring_available,
    new_credential_ref,
)
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.runtime import refuse_root, runtime_from_config
from open_transcribe.desktop.schema import CredentialRef, ManagedConfig


class _FailingBackend:
    """A backend that raises one chosen keyring error for every operation."""

    def __init__(self, error_name: str) -> None:
        self._error_name = error_name

    def __getattr__(self, name: str):
        import keyring.errors

        error = getattr(keyring.errors, self._error_name)

        def raise_it(*args: str) -> str:
            raise error(name)

        return raise_it


def test_a_missing_secret_service_is_an_error_not_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is no plaintext, file, or environment path to fall back to."""
    import secretstorage

    def unavailable_bus() -> None:
        raise secretstorage.exceptions.SecretServiceNotAvailableException(
            "The test session has no Secret Service."
        )

    # Simulate the missing service instead of depending on the developer's real keyring.
    monkeypatch.setattr(secretstorage, "dbus_init", unavailable_bus)
    with pytest.raises(DesktopError) as caught:
        SecretServiceCredentialStore()
    assert caught.value.code is DesktopErrorCode.KEYRING_UNAVAILABLE
    assert caught.value.recovery is not None
    assert keyring_available() is False


def test_a_locked_keyring_is_recoverable_and_never_downgrades() -> None:
    store = SecretServiceCredentialStore(backend=_FailingBackend("KeyringLocked"))
    with pytest.raises(DesktopError) as caught:
        store.get(CredentialRef(account="a"))
    assert caught.value.code is DesktopErrorCode.KEYRING_LOCKED


def test_a_broken_backend_reports_unavailable() -> None:
    store = SecretServiceCredentialStore(backend=_FailingBackend("KeyringError"))
    with pytest.raises(DesktopError) as caught:
        store.put(CredentialRef(account="a"), SecretStr("x"))
    assert caught.value.code is DesktopErrorCode.KEYRING_UNAVAILABLE


def test_an_empty_credential_is_refused() -> None:
    store = SecretServiceCredentialStore(backend=_FailingBackend("KeyringError"))
    with pytest.raises(DesktopError) as caught:
        store.put(CredentialRef(account="a"), SecretStr(""))
    # Refused before the backend is touched at all.
    assert caught.value.code is DesktopErrorCode.CREDENTIAL_MISSING


def test_every_replacement_mints_a_distinct_reference() -> None:
    first = new_credential_ref("0" * 32, "groq", "api_key")
    second = new_credential_ref("0" * 32, "groq", "api_key")
    assert first.account != second.account
    assert first.account.startswith("0" * 32 + ":groq:api_key:")


def test_managed_mode_ignores_ambient_environment(
    monkeypatch: pytest.MonkeyPatch, credentials: InMemoryCredentialStore
) -> None:
    """SEC-02: an exported OT_* variable or a stray .env cannot steer a client-launched engine."""
    monkeypatch.setenv("OT_GROQ__API_KEY", "attacker-key")
    monkeypatch.setenv("OT_SECURITY__AUTH_MODE", "none")
    monkeypatch.setenv("OT_HOST", "0.0.0.0")  # noqa: S104
    monkeypatch.setenv("OT_MAX_AUDIO_SIZE_MB", "1")
    ref = new_credential_ref("0" * 32, "groq", "api_key")
    credentials.put(ref, SecretStr("managed-key"))
    config = ManagedConfig(
        schema_version=1,
        installation_id="0" * 32,
        providers={"groq": {"enabled": True, "credentials": {"api_key": ref.model_dump()}}},
    )
    runtime = runtime_from_config(config, credentials=credentials)
    assert runtime.settings.groq.api_key is not None
    assert runtime.settings.groq.api_key.get_secret_value() == "managed-key"
    assert runtime.settings.max_audio_size_mb == 500
    assert runtime.settings.host == "127.0.0.1"


def test_a_dotenv_in_the_working_directory_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, credentials: InMemoryCredentialStore
) -> None:
    (tmp_path / ".env").write_text("OT_GROQ__API_KEY=from-dotenv\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    config = ManagedConfig(schema_version=1, installation_id="0" * 32)
    runtime = runtime_from_config(config, credentials=credentials)
    assert runtime.settings.groq.api_key is None


def test_an_enabled_provider_without_a_resolvable_key_stays_unconfigured(
    credentials: InMemoryCredentialStore,
) -> None:
    config = ManagedConfig(
        schema_version=1,
        installation_id="0" * 32,
        providers={"groq": {"enabled": True}},
    )
    runtime = runtime_from_config(config, credentials=credentials)
    assert runtime.unresolved_credentials == ("groq:api_key",)
    assert runtime.settings.groq.api_key is None


def test_the_managed_engine_never_starts_an_authenticated_http_deployment(
    credentials: InMemoryCredentialStore,
) -> None:
    config = ManagedConfig(schema_version=1, installation_id="0" * 32)
    runtime = runtime_from_config(config, credentials=credentials)
    assert runtime.settings.transport == "stdio"
    assert runtime.settings.security.auth_mode == "none"
    assert runtime.settings.result_store.backend == "disabled"


def test_setup_refuses_to_run_as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.geteuid", lambda: 0)
    with pytest.raises(DesktopError) as caught:
        refuse_root()
    assert caught.value.code is DesktopErrorCode.PRIVILEGE_REFUSED
