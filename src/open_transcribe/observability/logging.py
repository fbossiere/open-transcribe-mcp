import contextlib
import logging
import sys
from typing import Any, TextIO

import structlog


class _StderrLogger:
    """A logger that resolves stderr at write time rather than at configuration time.

    Binding the stream when logging is configured means a process that later replaces or closes
    its stderr — a test harness, a supervisor, a client that reopens the descriptor — turns every
    subsequent log call into an exception in whatever was being logged about. Operational output
    must never be able to take down the work it describes.
    """

    def msg(self, message: str) -> None:
        # stderr is gone. Losing a log line is acceptable; raising here is not.
        with contextlib.suppress(ValueError, OSError):
            print(message, file=sys.stderr, flush=True)  # noqa: T201 - this is the log sink

    log = debug = info = warn = warning = msg
    fatal = error = err = critical = exception = msg

    def __repr__(self) -> str:
        return "<StderrLogger>"


def _stderr_factory(*args: Any) -> _StderrLogger:
    return _StderrLogger()


def configure_logging(stream: TextIO | None = None) -> None:
    """Send operational output to stderr.

    stdout belongs to the MCP protocol under the stdio transport, and a log line on it would
    corrupt the stream. stderr is the correct destination for the HTTP deployment too.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(message)s", stream=stream or sys.stderr, force=True
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=(
            structlog.PrintLoggerFactory(file=stream) if stream is not None else _stderr_factory
        ),
    )
