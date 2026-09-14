"""The STDIO runner's own lifecycle: the sweeper it owns, and the cleanup it guarantees."""

import asyncio
from pathlib import Path

import pytest

from open_transcribe.desktop import stdio
from open_transcribe.desktop.credentials import InMemoryCredentialStore
from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.paths import DesktopPaths
from open_transcribe.desktop.runtime import ManagedRuntime, runtime_from_config
from open_transcribe.desktop.schema import ManagedConfig
from open_transcribe.desktop.tempaudio import TemporaryAudioArea


class _StubServer:
    """Stands in for FastMCP: it returns as soon as the client would close the pipe."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.transport: str | None = None

    async def run_async(self, transport: str, show_banner: bool = True) -> None:
        self.transport = transport
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error


def _runtime(paths: DesktopPaths, *, relay: bool) -> ManagedRuntime:
    config = ManagedConfig(
        schema_version=1,
        installation_id="0" * 32,
        privacy={"temporary_audio_processing": relay},
    )
    return runtime_from_config(config, credentials=InMemoryCredentialStore(), paths=paths)


async def test_the_runner_serves_stdio_and_never_asks_for_another_transport(
    desktop_paths: DesktopPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _StubServer()
    monkeypatch.setattr(stdio, "create_server", lambda *args: server)
    await stdio.serve(_runtime(desktop_paths, relay=False))
    assert server.transport == "stdio"


async def test_without_the_relay_permission_no_workspace_is_offered(
    desktop_paths: DesktopPaths,
) -> None:
    runtime = _runtime(desktop_paths, relay=False)
    assert runtime.temporary_audio is None
    assert stdio._workspace(runtime) is None


async def test_with_the_relay_permission_the_workspace_creates_owned_files(
    desktop_paths: DesktopPaths,
) -> None:
    runtime = _runtime(desktop_paths, relay=True)
    assert runtime.temporary_audio is not None
    create = stdio._workspace(runtime)
    assert create is not None
    path = Path(create())
    assert path.parent == runtime.temporary_audio.root
    assert path.exists()  # noqa: ASYNC240


async def test_the_runner_sweeps_what_it_owns_when_the_client_goes_away(
    desktop_paths: DesktopPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(desktop_paths, relay=True)
    area = runtime.temporary_audio
    assert area is not None
    stale = Path(area.create_file())
    # Simulate a file whose owner is gone: the runner must not leave it behind.
    (area.root / f"{stale.stem}.meta").unlink()

    monkeypatch.setattr(stdio, "create_server", lambda *args: _StubServer())
    await stdio.serve(runtime)
    assert not stale.exists()  # noqa: ASYNC240


async def test_a_serving_failure_still_runs_the_final_sweep(
    desktop_paths: DesktopPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(desktop_paths, relay=True)
    area = runtime.temporary_audio
    assert area is not None
    orphan = Path(area.create_file())
    (area.root / f"{orphan.stem}.meta").unlink()

    monkeypatch.setattr(stdio, "create_server", lambda *args: _StubServer(RuntimeError("pipe")))
    with pytest.raises(RuntimeError, match="pipe"):
        await stdio.serve(runtime)
    assert not orphan.exists()  # noqa: ASYNC240


async def test_the_periodic_sweeper_reclaims_expired_files(
    desktop_paths: DesktopPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stdio, "SWEEP_INTERVAL_SECONDS", 0.01)
    area = TemporaryAudioArea.for_runtime_dir(desktop_paths.runtime_dir, ttl_seconds=60)
    area.prepare()
    abandoned = Path(area.create_file())
    (area.root / f"{abandoned.stem}.meta").unlink()

    task = asyncio.create_task(stdio._sweep_forever(area))
    for _ in range(200):
        await asyncio.sleep(0.01)
        if not abandoned.exists():  # noqa: ASYNC240
            break
    task.cancel()
    assert not abandoned.exists()  # noqa: ASYNC240


class _FailingArea:
    """An area whose sweep always fails, to check the loop survives it."""

    def __init__(self) -> None:
        self.attempts = 0

    def sweep(self) -> None:
        self.attempts += 1
        raise OSError("the runtime directory went away")


async def test_a_sweep_failure_does_not_stop_the_sweeper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stdio, "SWEEP_INTERVAL_SECONDS", 0.01)
    area = _FailingArea()
    task = asyncio.create_task(stdio._sweep_forever(area))  # type: ignore[arg-type]
    for _ in range(200):
        await asyncio.sleep(0.01)
        if area.attempts >= 2:
            break
    task.cancel()
    assert area.attempts >= 2, "one failed sweep must not end the loop"


def test_a_relative_configuration_path_is_refused() -> None:
    with pytest.raises(DesktopError) as caught:
        stdio.require_managed_path(Path("config.toml"))
    assert caught.value.code is DesktopErrorCode.CONFIG_INVALID
    assert stdio.require_managed_path(Path("/etc/x.toml")) == Path("/etc/x.toml")


def test_run_stdio_resolves_the_configuration_and_serves(
    desktop_paths: DesktopPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from open_transcribe.desktop.store import save_managed_config

    save_managed_config(
        desktop_paths.config_file, ManagedConfig(schema_version=1, installation_id="0" * 32)
    )
    served: list[ManagedRuntime] = []

    async def record(runtime: ManagedRuntime) -> None:
        served.append(runtime)

    monkeypatch.setattr(stdio, "serve", record)
    stdio.run_stdio(desktop_paths.config_file)
    assert served[0].settings.transport == "stdio"
    assert served[0].settings.security.auth_mode == "none"
