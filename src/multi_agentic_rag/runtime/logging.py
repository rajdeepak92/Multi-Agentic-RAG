"""Runtime logging setup with file output and redaction."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog

from multi_agentic_rag.runtime.secrets import collect_secret_values, redact_secret_text


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts configured secret values."""

    def __init__(self, fmt: str, *, secrets: list[str] | None = None) -> None:
        super().__init__(fmt)
        self.secrets = secrets or collect_secret_values()

    def format(self, record: logging.LogRecord) -> str:
        return redact_secret_text(super().format(record), secrets=self.secrets)


def configure_runtime_logging(
    *,
    level: str,
    log_path: Path | None = None,
    debug: bool = False,
) -> None:
    """Configure console and optional file logs."""

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    if debug:
        numeric_level = logging.DEBUG
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    secrets = collect_secret_values()
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(numeric_level)
    console.setFormatter(RedactingFormatter("%(levelname)s %(message)s", secrets=secrets))
    root.addHandler(console)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s", secrets=secrets)
        )
        root.addHandler(file_handler)

    for noisy_logger in ("httpx", "httpcore", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        cache_logger_on_first_use=True,
    )


def _redact_event(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    return {key: redact_secret_text(str(value)) for key, value in event_dict.items()}
