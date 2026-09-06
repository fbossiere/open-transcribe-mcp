from abc import ABC, abstractmethod

from open_transcribe.domain.transcript import (
    CanonicalTranscript,
    DeleteResult,
    TranscriptChunk,
)


class ResultStore(ABC):
    @abstractmethod
    async def put(self, transcript: CanonicalTranscript) -> None: ...

    @abstractmethod
    async def get_chunk(
        self,
        transcript_id: str,
        cursor: str | None,
        max_chars: int,
        format: str,
    ) -> TranscriptChunk: ...

    @abstractmethod
    async def delete(self, transcript_id: str) -> DeleteResult: ...
