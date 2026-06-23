"""Structured logging setup."""

from __future__ import annotations

import logging

import structlog


class _Neo4jIdempotentSchemaNotificationFilter(logging.Filter):
    """Hide only Neo4j's harmless IF NOT EXISTS schema notification."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not (
            "Received notification from DBMS server" in message
            and "gql_status='00NA0'" in message
            and "index or constraint already exists" in message
        )


def configure_logging(level: str) -> None:
    """Configure stdlib and structlog once per process.

    Args:
        level: Logging level name such as `INFO`, `DEBUG`, or `WARNING`.
    """

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(message)s",
    )
    for noisy_logger in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    logging.getLogger("neo4j.notifications").addFilter(
        _Neo4jIdempotentSchemaNotificationFilter()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
