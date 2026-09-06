import io
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from open_transcribe.result_store.s3 import S3ResultStore
from open_transcribe.settings import ResultStoreSettings
from tests.unit.test_result_store import transcript


class FakePaginator:
    def __init__(self, client: "FakeS3") -> None:
        self.client = client

    def paginate(self, **_: Any) -> list[dict[str, Any]]:
        return [{"Contents": [{"Key": key} for key in self.client.objects]}]


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, dict[str, str]]] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = (kwargs["Body"], kwargs["Metadata"])

    def get_paginator(self, _: str) -> FakePaginator:
        return FakePaginator(self)

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        body, metadata = self.objects[kwargs["Key"]]
        return {"Body": io.BytesIO(body), "Metadata": metadata}

    def delete_object(self, **kwargs: Any) -> None:
        self.objects.pop(kwargs["Key"], None)


@pytest.mark.asyncio
async def test_s3_round_trip_and_idempotent_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeS3()
    monkeypatch.setitem(
        sys.modules, "boto3", SimpleNamespace(client=lambda *_args, **_kwargs: client)
    )
    store = S3ResultStore(
        ResultStoreSettings(
            backend="s3",
            cursor_secret="cursor-secret",
            s3_bucket="bucket",
            s3_endpoint_url="https://s3.example.com",
        )
    )
    item = transcript()
    await store.put(item)
    chunk = await store.get_chunk(item.transcript_id, None, 100, "text")
    assert chunk.content == item.text
    assert (await store.delete(item.transcript_id)).deleted
    assert not (await store.delete(item.transcript_id)).deleted
