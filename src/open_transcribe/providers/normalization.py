import re
from collections.abc import Hashable


def normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().replace("_", "-").split("-")[0].lower() or None


class SpeakerNormalizer:
    def __init__(self) -> None:
        self._mapping: dict[Hashable, str] = {}

    def normalize(self, value: Hashable | None) -> str | None:
        if value is None:
            return None
        key: Hashable = value
        if key not in self._mapping:
            self._mapping[key] = f"SPEAKER_{len(self._mapping) + 1:02d}"
        return self._mapping[key]


def provider_request_id(headers: object) -> str | None:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    for name in ("request-id", "x-request-id", "apim-request-id", "x-groq-request-id"):
        value = getter(name)
        if value:
            return str(value)[:200]
    return None


def safe_filename(media_type: str | None) -> str:
    suffixes = {
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/flac": ".flac",
        "audio/ogg": ".ogg",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
        "audio/webm": ".webm",
        "video/webm": ".webm",
    }
    normalized = re.sub(r"\s*;.*$", "", media_type or "").lower()
    return f"audio{suffixes.get(normalized, '.bin')}"
