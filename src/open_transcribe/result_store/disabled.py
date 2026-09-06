from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.domain.transcript import CanonicalTranscript, DeleteResult, TranscriptChunk
from open_transcribe.result_store.base import ResultStore


class DisabledResultStore(ResultStore):
    @staticmethod
    def _error() -> OpenTranscribeError:
        return OpenTranscribeError(
            ErrorCode.RESULT_STORE_DISABLED,
            "Temporary result storage is disabled. Use inline mode or configure a result store.",
        )

    async def put(self, transcript: CanonicalTranscript) -> None:
        raise self._error()

    async def get_chunk(
        self,
        transcript_id: str,
        cursor: str | None,
        max_chars: int,
        format: str,
    ) -> TranscriptChunk:
        raise self._error()

    async def delete(self, transcript_id: str) -> DeleteResult:
        raise self._error()
