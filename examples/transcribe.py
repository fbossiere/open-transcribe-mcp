"""Minimal FastMCP client example."""

import argparse
import asyncio
import json

from fastmcp import Client

DEFAULT_AUDIO_URL = (
    "https://raw.githubusercontent.com/fbossiere/open-transcribe-mcp/"
    "main/tests/fixtures/open-transcribe-bilingual.wav"
)


async def run(server_url: str, bearer_token: str, audio_url: str) -> None:
    async with Client(server_url, auth=bearer_token) as client:
        result = await client.call_tool(
            "transcribe_audio",
            {
                # No capability is stated, so the request routes to whichever provider is
                # configured; the response metadata reports what that model applied.
                "request": {
                    "source": {"type": "url", "url": audio_url},
                    "provider": "auto",
                    "routing_policy": "quality",
                }
            },
        )
        print(json.dumps(result.data, indent=2, ensure_ascii=False))  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_url", nargs="?", default=DEFAULT_AUDIO_URL)
    parser.add_argument("--server", default="http://localhost:8000/mcp")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.server, args.token, args.audio_url))


if __name__ == "__main__":
    main()
