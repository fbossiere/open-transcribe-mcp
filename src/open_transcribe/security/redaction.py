import hashlib
from urllib.parse import urlsplit, urlunsplit

REDACTED_QUERY = "[REDACTED]"
UNPARSEABLE_URL = "[UNPARSEABLE_URL]"


def redact_url(url: str) -> str:
    """Return a URL safe for exceptions and logs."""
    try:
        parts = urlsplit(url)
    except ValueError:
        # These run inside error and logging paths, on URLs a redirect may control, so a
        # URL that cannot be parsed must degrade to a placeholder rather than be echoed.
        return UNPARSEABLE_URL
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, REDACTED_QUERY if parts.query else "", "")
    )


def safe_source_fields(url: str) -> dict[str, str]:
    try:
        parts = urlsplit(url)
        host, path = parts.hostname or "", parts.path
    except ValueError:
        host, path = "", ""
    return {
        "source_host": host,
        "source_path_hash": hashlib.sha256(path.encode()).hexdigest()[:16],
    }
