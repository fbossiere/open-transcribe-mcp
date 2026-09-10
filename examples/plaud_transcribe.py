"""Transcribe a local recording (for example a Plaud export) with OpenTranscribe MCP.

OpenTranscribe accepts an HTTPS URL as its audio source. A file sitting on your own
laptop has no URL, so this helper publishes it on a loopback-only web server for the
duration of one request, asks the server to fetch it in `proxy` mode, and shuts the
web server down again. The audio never leaves your machine except on the call the
server makes to the speech-to-text provider you configured.

    uv run python examples/plaud_transcribe.py ~/Recordings/team-meeting.mp3

Requires `OT_SECURITY__REQUIRE_HTTPS_SOURCES=false` and `OT_SECURITY__ALLOW_PRIVATE_URLS=true`
on the server, which is only appropriate for a server bound to your own machine.
"""

import argparse
import asyncio
import mimetypes
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from fastmcp import Client
from mcp.shared.exceptions import MCPError

CHUNK_BYTES = 64 * 1024


def _guess_media_type(path: Path) -> str:
    media_type, _ = mimetypes.guess_type(path.name)
    return media_type or "application/octet-stream"


def _serve_once(path: Path) -> tuple[ThreadingHTTPServer, str]:
    """Serve exactly one file on 127.0.0.1 under an unguessable path."""
    secret = secrets.token_urlsafe(16)
    route = f"/{secret}/{path.name}"
    media_type = _guess_media_type(path)
    size = path.stat().st_size

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _headers(self) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", media_type)
            self.send_header("Content-Length", str(size))
            self.end_headers()

        def do_HEAD(self) -> None:
            if self.path != route:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._headers()

        def do_GET(self) -> None:
            if self.path != route:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._headers()
            with path.open("rb") as handle:
                while chunk := handle.read(CHUNK_BYTES):
                    self.wfile.write(chunk)

        def log_message(self, *_: Any) -> None:
            return

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}{route}"


def _timecode(milliseconds: int | None) -> str:
    if milliseconds is None:
        return "--:--"
    seconds = int(milliseconds) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def render(result: dict[str, Any]) -> str:
    segments = result.get("segments") or []
    if not segments:
        return (result.get("text") or "").strip()
    lines: list[str] = []
    previous_speaker = None
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        speaker = segment.get("speaker")
        stamp = _timecode(segment.get("start_ms"))
        if not speaker:
            lines.append(f"[{stamp}] {text}")
            continue
        if speaker != previous_speaker:
            if lines:
                lines.append("")
            lines.append(f"[{stamp}] {speaker}")
            previous_speaker = speaker
        lines.append(text)
    return "\n".join(lines).strip()


def explain(exc: BaseException, server: str) -> str:
    """Turn a client-side failure into one line a non-developer can act on."""
    if isinstance(exc, MCPError):
        return (
            "The server rejected the request. The usual cause is that the value passed to "
            "--token does not match OT_SECURITY__BEARER_TOKEN in your .env file."
        )
    if isinstance(exc, OSError) or "connect" in str(exc).lower():
        return (
            f"Could not reach OpenTranscribe at {server}. Check that the Terminal window "
            "running 'uv run open-transcribe-mcp' is still open and reports 'Uvicorn running'."
        )
    return f"{type(exc).__name__}: {exc}"


async def call_tool(server: str, token: str, request: dict[str, Any]) -> Any:
    async with Client(server, auth=token) as client:
        response = await client.call_tool("transcribe_audio", {"request": request})
    return response.data


def run(args: argparse.Namespace) -> int:
    audio = Path(args.audio).expanduser().resolve()
    if not audio.is_file():
        print(f"No such recording: {audio}")
        return 1

    httpd, url = _serve_once(audio)
    request: dict[str, Any] = {
        "source": {"type": "url", "url": url},
        "provider": args.provider,
        "routing_policy": args.policy,
        # Stated capabilities exclude models that cannot honour them. Speaker labels and
        # segment timestamps are what this script renders, so it asks for them; the
        # transcript style is left unset so a verbatim-only model stays reachable.
        "diarization": not args.no_diarization,
        "timestamps": "segment",
        "source_delivery": "proxy",
        "result_mode": "inline",
    }
    if args.language:
        request["language"] = args.language
    if args.speakers:
        request["speaker_count_hint"] = args.speakers

    try:
        print(f"Transcribing {audio.name} ({audio.stat().st_size / 1_000_000:.1f} MB)…")
        result = asyncio.run(call_tool(args.server, args.token, request))
    except Exception as exc:
        print(f"Failed: {explain(exc, args.server)}")
        return 2
    finally:
        httpd.shutdown()
        httpd.server_close()

    if isinstance(result, dict) and result.get("status") == "error":
        error = result.get("error", {})
        print(f"Failed: {error.get('code')} — {error.get('message')}")
        return 2

    transcript = render(result)
    destination = Path(args.out).expanduser() if args.out else audio.with_suffix(".txt")
    destination.write_text(transcript + "\n", encoding="utf-8")

    print(f"Provider: {result.get('provider')} / {result.get('model')}")
    languages = ", ".join(result.get("detected_languages") or []) or "not reported"
    print(f"Languages: {languages}")
    for warning in result.get("warnings") or []:
        print(f"Warning: {warning}")
    print(f"Saved: {destination}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe a local recording file.")
    parser.add_argument("audio", help="path to the audio file to transcribe")
    parser.add_argument("--server", default="http://localhost:8000/mcp")
    parser.add_argument(
        "--token",
        default=os.environ.get("OT_SECURITY__BEARER_TOKEN"),
        help="MCP bearer token (defaults to $OT_SECURITY__BEARER_TOKEN)",
    )
    parser.add_argument("--provider", default="auto")
    parser.add_argument(
        "--policy", default="quality", choices=["default", "quality", "cost", "latency"]
    )
    parser.add_argument("--language", help="BCP-47 tag, for example fr or en-US")
    parser.add_argument("--speakers", type=int, help="expected number of speakers")
    parser.add_argument("--no-diarization", action="store_true")
    parser.add_argument("--out", help="where to write the transcript (default: alongside audio)")
    args = parser.parse_args()
    if not args.token:
        parser.error("no token: pass --token or set OT_SECURITY__BEARER_TOKEN")
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
