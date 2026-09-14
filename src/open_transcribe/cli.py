"""The engine's command line.

Invoked with no arguments it starts the existing authenticated HTTP deployment, unchanged. The
subcommands add the local desktop transport and the administration commands that must never be
reachable as MCP tools.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

_DESCRIPTION = "Provider-independent speech-to-text over MCP."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="open-transcribe-mcp", description=_DESCRIPTION)
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="Run the MCP server.")
    serve.add_argument(
        "--transport",
        choices=("http", "stdio"),
        default="http",
        help="http: the authenticated network deployment. stdio: one local client-owned process.",
    )
    serve.add_argument(
        "--config",
        type=Path,
        default=None,
        metavar="PATH",
        help="Absolute path to a managed desktop configuration. Required for --transport stdio.",
    )

    doctor = commands.add_parser("doctor", help="Report the state of a managed installation.")
    doctor.add_argument("--config", type=Path, required=True, metavar="PATH")
    doctor.add_argument("--json", action="store_true", help="Emit the typed report as JSON.")
    doctor.add_argument(
        "--check-engine",
        action="store_true",
        help="Also start the packaged engine and verify its MCP handshake.",
    )

    cleanup = commands.add_parser(
        "cleanup-temporary-audio",
        help="Delete expired temporary audio owned by this installation.",
    )
    cleanup.add_argument("--config", type=Path, required=True, metavar="PATH")
    cleanup.add_argument(
        "--purge",
        action="store_true",
        help="Delete every owned temporary file, not only the expired ones.",
    )
    return parser


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = getattr(args, "command", None)
    if command is None:
        from open_transcribe.server import serve_http
        from open_transcribe.settings import get_settings

        serve_http(get_settings())
        return 0
    if command == "serve":
        return _serve(args)
    if command == "doctor":
        return _doctor(args)
    return _cleanup(args)


def _serve(args: argparse.Namespace) -> int:
    from open_transcribe.server import serve_http
    from open_transcribe.settings import get_settings

    if args.transport == "http":
        if args.config is not None:
            _fail("--config applies to the stdio transport only.")
            return 2
        serve_http(get_settings())
        return 0
    if args.config is None:
        _fail("--transport stdio requires --config with an absolute configuration path.")
        return 2
    return _serve_stdio(args.config)


def _serve_stdio(config_path: Path) -> int:
    from open_transcribe.desktop.errors import DesktopError
    from open_transcribe.desktop.stdio import run_stdio

    try:
        run_stdio(config_path)
    except DesktopError as exc:
        _fail(f"{exc.code.value}: {exc.message}")
        if exc.recovery:
            _fail(exc.recovery)
        return 1
    return 0


def _doctor(args: argparse.Namespace) -> int:
    from open_transcribe.desktop.diagnostics import Severity, run_diagnostics

    report = run_diagnostics(args.config, check_engine=args.check_engine)
    if args.json:
        json.dump(report.to_export(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        for check in report.checks:
            sys.stdout.write(f"{check.severity.value.upper():8} {check.check_id}: {check.title}\n")
            if check.recovery:
                sys.stdout.write(f"         -> {check.recovery}\n")
    return 1 if report.worst is Severity.ERROR else 0


def _cleanup(args: argparse.Namespace) -> int:
    from open_transcribe.desktop.errors import DesktopError
    from open_transcribe.desktop.paths import DesktopPaths
    from open_transcribe.desktop.store import load_managed_config
    from open_transcribe.desktop.tempaudio import TemporaryAudioArea

    try:
        config = load_managed_config(args.config)
        area = TemporaryAudioArea.for_runtime_dir(
            DesktopPaths.resolve().runtime_dir,
            ttl_seconds=config.privacy.temporary_audio_ttl_seconds,
        )
    except DesktopError as exc:
        # The timer must stay quiet and harmless when the installation is gone or unreadable.
        _fail(f"{exc.code.value}: {exc.message}")
        return 0
    report = area.purge() if args.purge else area.sweep()
    _fail(f"removed={report.removed} retained={report.retained} failed={len(report.failed)}")
    return 0 if report.complete else 1


def _fail(message: str) -> None:
    sys.stderr.write(f"{message}\n")


if __name__ == "__main__":
    raise SystemExit(run_cli())
