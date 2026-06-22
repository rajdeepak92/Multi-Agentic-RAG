"""Small stdlib logging setup used by graph entrypoints."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_command_logging(level: str = "INFO", log_path: Path | None = None) -> logging.Logger:
    """Configure framework logging for one command run."""

    logger = logging.getLogger("multi_agentic_rag")
    logger.setLevel(level.upper())
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    if not logger.handlers:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    if log_path is not None and not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_path.resolve()
        for handler in logger.handlers
    ):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger
