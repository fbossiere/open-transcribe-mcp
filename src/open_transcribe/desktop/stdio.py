"""The local STDIO transport used by a desktop MCP client.

The client owns this process. Closing OpenTranscribe Setup does not stop it, and this process
opens no listening socket: its only channels are the pipes the client created.
"""

import asyncio
import contextlib
from pathlib import Path

import structlog

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode
from open_transcribe.desktop.runtime import ManagedRuntime, build_managed_runtime
from open_transcribe.desktop.tempaudio import SWEEP_INTERVAL_SECONDS, TemporaryAudioArea
from open_transcribe.observability.logging import configure_logging
from open_transcribe.server import create_server
from open_transcribe.sources.resolver import TemporaryFileFactory

logger = structlog.get_logger()


def run_stdio(config_path: Path) -> None:
    """Serve MCP over stdin and stdout under an explicit managed configuration."""
    configure_logging()
    runtime = build_managed_runtime(config_path.resolve())
    asyncio.run(serve(runtime))


async def serve(runtime: ManagedRuntime) -> None:
    from fastmcp import FastMCP

    workspace = _workspace(runtime)
    server: FastMCP = create_server(runtime.settings, runtime.policy, workspace)
    logger.info(
        "stdio_engine_starting",
        enabled_providers=sorted(runtime.policy.enabled_providers or ()),
        cross_provider_fallback=runtime.policy.allow_cross_provider_fallback,
        temporary_audio=runtime.policy.allow_temporary_audio,
        unresolved_credentials=list(runtime.unresolved_credentials),
        credential_error=runtime.credential_error,
    )
    sweeper = (
        asyncio.create_task(_sweep_forever(runtime.temporary_audio))
        if runtime.temporary_audio is not None
        else None
    )
    try:
        # FastMCP returns when the client closes the pipe; in-flight work is cancelled with it.
        await server.run_async(transport="stdio", show_banner=False)
    finally:
        if sweeper is not None:
            sweeper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sweeper
        if runtime.temporary_audio is not None:
            # Leave nothing this process owns behind, and never detach a background worker.
            runtime.temporary_audio.sweep()
        logger.info("stdio_engine_stopped")


def _workspace(runtime: ManagedRuntime) -> TemporaryFileFactory | None:
    if runtime.temporary_audio is None:
        return None
    area = runtime.temporary_audio

    def create() -> str:
        return area.create_file()

    return create


async def _sweep_forever(area: TemporaryAudioArea) -> None:
    """Reclaim expired audio while this engine is alive.

    Expired data may survive until the next pass, and a suspended machine cannot promise
    wall-clock erasure; the desktop documentation states both.
    """
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            report = await asyncio.to_thread(area.sweep)
        except OSError:
            logger.warning("temporary_audio_sweep_failed")
            continue
        if report.removed or report.failed:
            logger.info("temporary_audio_swept", removed=report.removed, failed=len(report.failed))


def require_managed_path(value: Path) -> Path:
    if not value.is_absolute():
        raise DesktopError(
            DesktopErrorCode.CONFIG_INVALID,
            "A managed configuration must be given as an absolute path.",
        )
    return value
