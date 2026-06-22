"""Structured logging setup."""

from __future__ import annotations

import logging

import structlog


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
