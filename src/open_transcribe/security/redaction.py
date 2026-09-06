import hashlib
from urllib.parse import urlsplit, urlunsplit

REDACTED_QUERY = "[REDACTED]"


def redact_url(url: str) -> str:
    """Return a URL safe for exceptions and logs."""
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, REDACTED_QUERY if parts.query else "", "")
    )


def safe_source_fields(url: str) -> dict[str, str]:
    parts = urlsplit(url)
    path_hash = hashlib.sha256(parts.path.encode()).hexdigest()[:16]
    return {"source_host": parts.hostname or "", "source_path_hash": path_hash}
