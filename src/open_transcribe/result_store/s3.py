import asyncio
import gzip
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.domain.transcript import CanonicalTranscript, DeleteResult, TranscriptChunk
from open_transcribe.result_store.base import ResultStore
from open_transcribe.result_store.chunks import get_chunk_from_transcript
from open_transcribe.result_store.cursor import CursorCodec
from open_transcribe.settings import ResultStoreSettings


class S3ResultStore(ResultStore):
    """S3-compatible, gzip-compressed temporary canonical transcripts."""

    def __init__(self, settings: ResultStoreSettings) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "Install open-transcribe-mcp[s3] to use the S3 result store"
            ) from exc
        if not settings.s3_bucket or settings.cursor_secret is None:
            raise RuntimeError("S3 result store settings are incomplete")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.ttl_seconds = settings.ttl_seconds
        self.codec = CursorCodec(settings.cursor_secret.get_secret_value())
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=str(settings.s3_endpoint_url) if settings.s3_endpoint_url else None,
            region_name=settings.s3_region,
        )

    def _key(self, transcript_id: str, now: datetime | None = None) -> str:
        instant = now or datetime.now(UTC)
        return f"{self.prefix}/{instant:%Y/%m/%d}/{transcript_id}.json.gz"

    async def put(self, transcript: CanonicalTranscript) -> None:
        key = self._key(transcript.transcript_id)
        content = gzip.compress(transcript.model_dump_json().encode())
        expires = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType="application/json",
            ContentEncoding="gzip",
            Metadata={"expires-at": expires.isoformat()},
            ServerSideEncryption="AES256",
        )

    async def _find(self, transcript_id: str) -> tuple[str, CanonicalTranscript]:
        suffix = f"/{transcript_id}.json.gz"

        def load() -> tuple[str, bytes, dict[str, str]]:
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{self.prefix}/"):
                for item in page.get("Contents", []):
                    key = str(item["Key"])
                    if key.endswith(suffix):
                        response = self.client.get_object(Bucket=self.bucket, Key=key)
                        return key, response["Body"].read(), response.get("Metadata", {})
            raise KeyError(transcript_id)

        try:
            key, raw, metadata = await asyncio.to_thread(load)
        except KeyError as exc:
            raise OpenTranscribeError(
                ErrorCode.RESULT_NOT_FOUND, "Transcript not found or expired."
            ) from exc
        expires_at = metadata.get("expires-at")
        if expires_at and datetime.fromisoformat(expires_at) <= datetime.now(UTC):
            await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
            raise OpenTranscribeError(
                ErrorCode.RESULT_NOT_FOUND, "Transcript not found or expired."
            )
        try:
            return key, CanonicalTranscript.model_validate_json(gzip.decompress(raw))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise OpenTranscribeError(
                ErrorCode.INTERNAL_ERROR, "The stored transcript is invalid."
            ) from exc

    async def get_chunk(
        self,
        transcript_id: str,
        cursor: str | None,
        max_chars: int,
        format: str,
    ) -> TranscriptChunk:
        _, transcript = await self._find(transcript_id)
        return get_chunk_from_transcript(
            transcript, transcript_id, cursor, max_chars, format, self.codec
        )

    async def delete(self, transcript_id: str) -> DeleteResult:
        try:
            key, _ = await self._find(transcript_id)
        except OpenTranscribeError as exc:
            if exc.response.code == ErrorCode.RESULT_NOT_FOUND:
                return DeleteResult(transcript_id=transcript_id, deleted=False)
            raise
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)
        return DeleteResult(transcript_id=transcript_id, deleted=True)
