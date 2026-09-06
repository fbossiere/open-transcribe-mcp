"""Minimal FastMCP client example."""

import argparse
import asyncio
import json

from fastmcp import Client


async def run(server_url: str, bearer_token: str, audio_url: str) -> None:
    async with Client(server_url, auth=bearer_token) as client:
        result = await client.call_tool(
            "transcribe_audio",
            {
                "request": {
                    "source": {"type": "url", "url": audio_url},
                    "provider": "auto",
                    "routing_policy": "quality",
                    "diarization": True,
                    "timestamps": "segment",
                    "transcript_style": "clean",
                }
            },
        )
        print(json.dumps(result.data, indent=2, ensure_ascii=False))  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_url")
    parser.add_argument("--server", default="http://localhost:8000/mcp")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.server, args.token, args.audio_url))


if __name__ == "__main__":
    main()
