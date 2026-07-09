"""structlog setup for parser-universal.

JSON output by default (`UP_LOG_FORMAT=console` switches to human-readable
dev console). Bound-context helpers for `source=`, `run_id=` etc.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

_CONFIGURED = False


def configure_logging(level: str = "INFO", json: bool | None = None) -> None:
    """Idempotent structlog + stdlib configuration.

    Args:
        level: log level for stdlib root logger ("DEBUG" / "INFO" / "WARNING").
        json: override renderer. If None, honors `UP_LOG_FORMAT` env ("json"|"console").
              Defaults to JSON.
    """
    global _CONFIGURED
    if json is None:
        json = os.environ.get("UP_LOG_FORMAT", "json").lower() != "console"

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.CallsiteParameterAdder(
            parameters=[structlog.processors.CallsiteParameter.MODULE],
        ),
    ]
    if json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )

    # Bridge stdlib `logging.getLogger()` calls into structlog.
    # Reconfigure every call so tests that swap sys.stderr can intercept.
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    _CONFIGURED = True


def get_logger(name: str) -> Any:
    """Return a bound structlog logger. Always configures if not yet done."""
    if not _CONFIGURED:
        configure_logging()
    return structlog.get_logger(name)


__all__ = ["configure_logging", "get_logger"]
