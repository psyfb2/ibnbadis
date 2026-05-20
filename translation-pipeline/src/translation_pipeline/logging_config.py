"""Structured logging setup (structlog -> JSON to stdout).

Trade-off (KISS): the org standard suggests OpenTelemetry, but for a local,
single-operator, batch CLI that is over-engineering. Structured JSON logs satisfy
the diagnosability requirement; OTel is explicitly deferred (reconciled in repo
docs in task 6).

``SecretStr`` is rendered via ``repr`` by structlog, which masks the value, so a
``Settings`` object logged in an event dict never leaks the password.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import structlog


def configure_logging(level: str | None = None) -> None:
    """Configure structlog to emit JSON lines to stdout.

    Args:
        level: log level name; defaults to the ``LOG_LEVEL`` env var or ``INFO``.
    """
    level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, level_name, logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # ensure_ascii=False keeps Arabic literal in log output.
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a bound structlog logger (configures with defaults if needed)."""
    if not structlog.is_configured():
        configure_logging()
    return structlog.get_logger(name)
