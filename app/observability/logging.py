"""
Structured logging setup using structlog.

Why structlog instead of standard logging?
  - Outputs JSON in production → easily parsed by SigNoz / Grafana / CloudWatch
  - Automatically includes trace_id and span_id in every log line
  - Context variables (tenant_id, chat_id) flow through without manual passing
  - Human-readable in development (colored, formatted)

Usage:
    from app.observability.logging import get_logger
    logger = get_logger(__name__)

    logger.info("ingress:accept", tenant_id=tenant_id, chat_id=chat_id, text_len=42)

Call setup_logging() once at app startup.
"""

from __future__ import annotations

import logging
import os
import sys

import structlog


def setup_logging() -> None:
    """
    Configure structlog + standard logging.

    In production (APP_ENV=production): outputs JSON.
    In development: outputs colored, human-readable text.
    """
    app_env = os.environ.get("APP_ENV", "development")
    is_prod = app_env == "production"
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Standard library logging — used by SQLAlchemy, uvicorn, etc.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level, logging.INFO),
    )

    # Silence noisy libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_trace_context,  # inject OTel trace_id + span_id
    ]

    if is_prod:
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level, logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _add_trace_context(logger, method, event_dict: dict) -> dict:
    """
    Inject the current OTel trace_id and span_id into every log line.

    This links log lines to traces in SigNoz — you can click a log and
    jump directly to the corresponding trace.
    """
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:
        pass
    return event_dict


def get_logger(name: str):
    """Get a structlog logger bound to the given name."""
    return structlog.get_logger(name)
