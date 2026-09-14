"""Verifying that the exact packaged engine answers MCP under the committed configuration.

This uses the locked MCP client implementation rather than a hand-rolled protocol, negotiates
normally, bounds the whole operation, and stops only the subprocess it created.
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from open_transcribe.desktop.errors import DesktopError, DesktopErrorCode

EXPECTED_TOOLS = frozenset(
    {
        "transcribe_audio",
        "get_transcript_chunk",
        "delete_transcript",
        "list_transcription_models",
        "estimate_transcription_cost",
    }
)

HANDSHAKE_TIMEOUT_SECONDS = 30.0
"""Initialization and tool discovery together. Reviewed against the real schemas before release."""

MAX_PROTOCOL_BYTES = 512 * 1024


@dataclass(frozen=True, slots=True)
class EngineProbeResult:
    ok: bool
    reason: str
    server_name: str | None = None
    server_version: str | None = None
    protocol_version: str | None = None
    tools: tuple[str, ...] = field(default_factory=tuple)
    unexpected_tools: tuple[str, ...] = field(default_factory=tuple)
    missing_tools: tuple[str, ...] = field(default_factory=tuple)


def engine_command(executable: Path, config_path: Path) -> list[str]:
    """The exact argument vector a client must use. Fixed array, no shell, absolute paths."""
    return [str(executable), "serve", "--transport", "stdio", "--config", str(config_path)]


def probe_engine(executable: Path, config_path: Path) -> EngineProbeResult:
    return asyncio.run(probe_engine_async(executable, config_path))


def require_executable(executable: Path) -> None:
    if executable.is_file() and os.access(executable, os.X_OK):
        return
    raise DesktopError(
        DesktopErrorCode.ENGINE_MISSING,
        "The packaged transcription engine is missing or not executable.",
        recovery="Reinstall the OpenTranscribe Setup package.",
    )


async def probe_engine_async(executable: Path, config_path: Path) -> EngineProbeResult:
    await asyncio.to_thread(require_executable, executable)
    command = engine_command(executable, config_path)
    try:
        async with asyncio.timeout(HANDSHAKE_TIMEOUT_SECONDS):
            return await _handshake(command)
    except TimeoutError:
        return EngineProbeResult(ok=False, reason="engine.timeout")


async def _handshake(command: list[str]) -> EngineProbeResult:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=command[0],
        args=command[1:],
        # A deliberately minimal environment: the managed engine must not need, and must not be
        # able to be steered by, anything the parent session happens to export.
        env={"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/nonexistent")},
    )
    try:
        # The engine's stderr is discarded rather than captured: it is untrusted subprocess
        # output that may carry provider or path detail, it is never shown, and sending it to
        # the null device is also the only bound that a noisy process cannot exceed.
        with open(os.devnull, "w", encoding="utf-8") as errlog:  # noqa: ASYNC230
            async with (
                stdio_client(parameters, errlog=errlog) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                initialized = await session.initialize()
                listing = await session.list_tools()
    except TimeoutError:
        # The caller's whole-operation deadline; reported as a timeout, not a protocol failure.
        raise
    except Exception:
        # The transport wraps failures in an exception group. Nothing from the engine's stderr is
        # shown: it is untrusted output and may carry provider or path detail.
        return EngineProbeResult(ok=False, reason="engine.handshake_failed")

    payload = json.dumps([tool.model_dump(mode="json") for tool in listing.tools])
    if len(payload.encode()) > MAX_PROTOCOL_BYTES:
        return EngineProbeResult(ok=False, reason="engine.output_too_large")

    names = frozenset(tool.name for tool in listing.tools)
    unexpected = tuple(sorted(names - EXPECTED_TOOLS))
    missing = tuple(sorted(EXPECTED_TOOLS - names))
    invalid = tuple(
        sorted(tool.name for tool in listing.tools if not isinstance(tool.input_schema, dict))
    )
    ok = not unexpected and not missing and not invalid
    return EngineProbeResult(
        ok=ok,
        # A swapped engine is a failure, never something to accept quietly.
        reason="engine.ready" if ok else "engine.unexpected_tools",
        server_name=initialized.server_info.name,
        server_version=initialized.server_info.version,
        protocol_version=str(initialized.protocol_version),
        tools=tuple(sorted(names)),
        unexpected_tools=unexpected,
        missing_tools=missing,
    )
