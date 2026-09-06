from uuid import uuid4

import pytest

from open_transcribe.domain.audio import TimestampMode, TranscriptStyle
from open_transcribe.domain.errors import ErrorCode, OpenTranscribeError
from open_transcribe.domain.transcript import (
    CanonicalTranscript,
    TranscriptionMetadata,
    TranscriptSegment,
    UsageInfo,
)
from open_transcribe.result_store.memory import MemoryResultStore


def transcript() -> CanonicalTranscript:
    return CanonicalTranscript(
        transcript_id=f"tr_{uuid4().hex}",
        provider="test",
        model="test-model",
        text="abcdefghij",
        segments=[
            TranscriptSegment(start_ms=0, end_ms=100, text="abc"),
            TranscriptSegment(start_ms=100, end_ms=200, text="def"),
        ],
        usage=UsageInfo(audio_seconds=0.2),
        metadata=TranscriptionMetadata(
            diarization=False,
            timestamps=TimestampMode.SEGMENT,
            transcript_style=TranscriptStyle.VERBATIM,
        ),
    )


@pytest.mark.asyncio
async def test_text_chunks_have_signed_retryable_cursors() -> None:
    store = MemoryResultStore(ttl_seconds=60, cursor_secret="secret")
    item = transcript()
    await store.put(item)
    first = await store.get_chunk(item.transcript_id, None, 4, "text")
    assert first.content == "abcd"
    assert first.next_cursor
    assert not first.done
    retry = await store.get_chunk(item.transcript_id, None, 4, "text")
    assert retry.next_cursor == first.next_cursor
    second = await store.get_chunk(item.transcript_id, first.next_cursor, 10, "text")
    assert second.content == "efghij"
    assert second.done


@pytest.mark.asyncio
async def test_tampered_cursor_is_rejected() -> None:
    store = MemoryResultStore(ttl_seconds=60, cursor_secret="secret")
    item = transcript()
    await store.put(item)
    with pytest.raises(OpenTranscribeError) as caught:
        await store.get_chunk(item.transcript_id, "tampered", 10, "text")
    assert caught.value.response.code == ErrorCode.RESULT_NOT_FOUND


@pytest.mark.asyncio
async def test_delete_is_idempotent() -> None:
    store = MemoryResultStore(ttl_seconds=60, cursor_secret="secret")
    item = transcript()
    await store.put(item)
    assert (await store.delete(item.transcript_id)).deleted
    assert not (await store.delete(item.transcript_id)).deleted


@pytest.mark.asyncio
async def test_segment_chunks_and_cursor_binding() -> None:
    store = MemoryResultStore(ttl_seconds=60, cursor_secret="secret")
    item = transcript()
    await store.put(item)
    first = await store.get_chunk(item.transcript_id, None, 120, "segments")
    assert isinstance(first.content, list)
    if first.next_cursor:
        with pytest.raises(OpenTranscribeError, match="does not belong"):
            await store.get_chunk(item.transcript_id, first.next_cursor, 120, "text")


@pytest.mark.asyncio
async def test_invalid_chunk_arguments() -> None:
    store = MemoryResultStore(ttl_seconds=60, cursor_secret="secret")
    item = transcript()
    await store.put(item)
    with pytest.raises(OpenTranscribeError, match="format"):
        await store.get_chunk(item.transcript_id, None, 100, "html")
    with pytest.raises(OpenTranscribeError, match="max_chars"):
        await store.get_chunk(item.transcript_id, None, 0, "text")
