"""SEC-03 and PKG-06: the managed configuration fails safe and never mutates what it cannot read."""

import os
import stat
from pathlib import Path

import pytest

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.paths import DesktopPaths, ensure_private_dir, write_private_file
from open_transcribe.desktop.schema import SCHEMA_VERSION, ManagedConfig
from open_transcribe.desktop.store import (
    installation_lock,
    load_managed_config,
    save_managed_config,
)


def test_round_trip_preserves_the_profile(tmp_path: Path, managed_config: ManagedConfig) -> None:
    path = tmp_path / "config.toml"
    config = ManagedConfig.model_validate(
        managed_config.model_dump() | {"providers": {"groq": {"enabled": True}}, "locale": "fr"}
    )
    save_managed_config(path, config)
    loaded = load_managed_config(path)
    assert loaded.enabled_providers == {"groq"}
    assert loaded.locale == "fr"


def test_saved_configuration_is_private(tmp_path: Path, managed_config: ManagedConfig) -> None:
    path = tmp_path / "desktop" / "config.toml"
    save_managed_config(path, managed_config)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_newer_schema_is_refused_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    original = f'schema_version = {SCHEMA_VERSION + 1}\ninstallation_id = "{"0" * 32}"\n'
    write_private_file(path, original.encode())
    with pytest.raises(DesktopError) as caught:
        load_managed_config(path)
    assert caught.value.code is DesktopErrorCode.CONFIG_UNSUPPORTED_VERSION
    assert path.read_text(encoding="utf-8") == original


def test_a_missing_version_is_invalid_rather_than_a_downgrade(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_private_file(path, b'installation_id = "0"\n')
    with pytest.raises(DesktopError) as caught:
        load_managed_config(path)
    assert caught.value.code is DesktopErrorCode.CONFIG_INVALID


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    document = f'schema_version = 1\ninstallation_id = "{"0" * 32}"\nsend_everything = true\n'
    write_private_file(path, document.encode())
    with pytest.raises(DesktopError) as caught:
        load_managed_config(path)
    assert caught.value.code is DesktopErrorCode.CONFIG_INVALID


def test_a_symlinked_configuration_is_refused(
    tmp_path: Path, managed_config: ManagedConfig
) -> None:
    real = tmp_path / "real.toml"
    save_managed_config(real, managed_config)
    link = tmp_path / "config.toml"
    link.symlink_to(real)
    with pytest.raises(DesktopError) as caught:
        load_managed_config(link)
    assert caught.value.code is DesktopErrorCode.CONFIG_UNSAFE_LOCATION


def test_a_world_readable_configuration_is_refused(
    tmp_path: Path, managed_config: ManagedConfig
) -> None:
    path = tmp_path / "config.toml"
    save_managed_config(path, managed_config)
    path.chmod(0o644)
    with pytest.raises(DesktopError) as caught:
        load_managed_config(path)
    assert caught.value.code is DesktopErrorCode.CONFIG_UNSAFE_LOCATION
    assert caught.value.recovery is not None


def test_a_relative_path_is_refused(managed_config: ManagedConfig) -> None:
    with pytest.raises(DesktopError):
        load_managed_config(Path("config.toml"))


def test_an_interrupted_write_leaves_the_previous_version(
    tmp_path: Path, managed_config: ManagedConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"
    save_managed_config(path, managed_config)
    original = path.read_bytes()

    real_replace = os.replace

    def explode(src: object, dst: object) -> None:
        raise OSError("interrupted")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError, match="interrupted"):
        save_managed_config(path, managed_config.model_copy(update={"locale": "fr"}))
    monkeypatch.setattr(os, "replace", real_replace)
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".config.toml.*.tmp"))


def test_concurrent_writers_serialize(desktop_paths: DesktopPaths) -> None:
    ensure_private_dir(desktop_paths.state_dir)

    def take_second_lock() -> None:
        with installation_lock(desktop_paths):
            pass

    with installation_lock(desktop_paths), pytest.raises(DesktopError) as caught:
        take_second_lock()
    assert caught.value.code is DesktopErrorCode.CONFIG_LOCKED
    # The lock is released again, so a later operation is not permanently blocked.
    with installation_lock(desktop_paths):
        pass


def test_a_preferred_provider_must_be_enabled() -> None:
    with pytest.raises(ValueError, match="not enabled"):
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            providers={"groq": {"enabled": False}},
            selection={"provider": "groq"},
        )


def test_credential_references_stay_in_the_application_namespace() -> None:
    with pytest.raises(ValueError, match="scope"):
        ManagedConfig(
            schema_version=1,
            installation_id="0" * 32,
            providers={
                "groq": {"credentials": {"api_key": {"service": "elsewhere", "account": "a"}}}
            },
        )
