import time

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.domain.transcript import CanonicalTranscript, DeleteResult, TranscriptChunk
from open_transcribe.result_store.base import ResultStore
from open_transcribe.result_store.chunks import get_chunk_from_transcript
from open_transcribe.result_store.cursor import CursorCodec


class MemoryResultStore(ResultStore):
    def __init__(self, *, ttl_seconds: int, cursor_secret: str) -> None:
        self.ttl_seconds = ttl_seconds
        self.codec = CursorCodec(cursor_secret)
        self._items: dict[str, tuple[float, CanonicalTranscript]] = {}

    async def put(self, transcript: CanonicalTranscript) -> None:
        self._items[transcript.transcript_id] = (time.monotonic() + self.ttl_seconds, transcript)

    def _get(self, transcript_id: str) -> CanonicalTranscript:
        item = self._items.get(transcript_id)
        if item is None or item[0] <= time.monotonic():
            self._items.pop(transcript_id, None)
            raise OpenTranscribeError(
                ErrorCode.RESULT_NOT_FOUND, "Transcript not found or expired."
            )
        return item[1]

    async def get_chunk(
        self,
        transcript_id: str,
        cursor: str | None,
        max_chars: int,
        format: str,
    ) -> TranscriptChunk:
        return get_chunk_from_transcript(
            self._get(transcript_id), transcript_id, cursor, max_chars, format, self.codec
        )

    async def delete(self, transcript_id: str) -> DeleteResult:
        deleted = self._items.pop(transcript_id, None) is not None
        return DeleteResult(transcript_id=transcript_id, deleted=deleted)
