from open_transcribe.result_store.base import ResultStore
from open_transcribe.result_store.disabled import DisabledResultStore
from open_transcribe.result_store.memory import MemoryResultStore
from open_transcribe.result_store.s3 import S3ResultStore
from open_transcribe.settings import Settings


def create_result_store(settings: Settings) -> ResultStore:
    config = settings.result_store
    if config.backend == "disabled":
        return DisabledResultStore()
    if config.cursor_secret is None:
        raise RuntimeError("result store cursor secret is missing")
    if config.backend == "memory":
        return MemoryResultStore(
            ttl_seconds=config.ttl_seconds,
            cursor_secret=config.cursor_secret.get_secret_value(),
        )
    return S3ResultStore(config)
