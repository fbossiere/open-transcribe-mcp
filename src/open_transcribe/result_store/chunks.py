import json

from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.domain.transcript import (
    CanonicalTranscript,
    TranscriptChunk,
    TranscriptSegment,
)
from open_transcribe.result_store.cursor import CursorCodec


def get_chunk_from_transcript(
    transcript: CanonicalTranscript,
    transcript_id: str,
    cursor: str | None,
    max_chars: int,
    format: str,
    codec: CursorCodec,
) -> TranscriptChunk:
    if format not in {"text", "segments"}:
        raise OpenTranscribeError(
            ErrorCode.RESULT_NOT_FOUND, "Chunk format must be text or segments."
        )
    if not 1 <= max_chars <= 50_000:
        raise OpenTranscribeError(
            ErrorCode.RESULT_NOT_FOUND, "max_chars must be between 1 and 50000."
        )
    index = 0
    if cursor:
        payload = codec.decode(cursor)
        if payload.get("id") != transcript_id or payload.get("format") != format:
            raise OpenTranscribeError(
                ErrorCode.RESULT_NOT_FOUND, "The cursor does not belong to this transcript."
            )
        index = int(payload.get("index", 0))
    if format == "text":
        text = transcript.text or ""
        text_content = text[index : index + max_chars]
        content: str | list[TranscriptSegment] = text_content
        next_index = index + len(text_content)
        done = next_index >= len(text)
    else:
        segments = transcript.segments or []
        selected: list[TranscriptSegment] = []
        used = 0
        next_index = index
        while next_index < len(segments):
            size = len(json.dumps(segments[next_index].model_dump(mode="json")))
            if selected and used + size > max_chars:
                break
            if not selected and size > max_chars:
                raise OpenTranscribeError(
                    ErrorCode.RESULT_NOT_FOUND,
                    "max_chars is smaller than the next serialized segment.",
                )
            selected.append(segments[next_index])
            used += size
            next_index += 1
        content = selected
        done = next_index >= len(segments)
    next_cursor = None
    if not done:
        next_cursor = codec.encode({"id": transcript_id, "format": format, "index": next_index})
    return TranscriptChunk(content=content, next_cursor=next_cursor, done=done)
