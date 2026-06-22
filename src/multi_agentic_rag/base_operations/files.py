"""Supported document file validation."""

from __future__ import annotations

from pathlib import Path

from multi_agentic_rag.common_defs import SUPPORTED_DOCUMENT_SUFFIXES
from multi_agentic_rag.exceptions import ConfigError


def ensure_supported_document(path: str | Path) -> Path:
    """Return a resolved document path after existence and suffix validation."""

    resolved = Path(path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise ConfigError(f"Document does not exist: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_DOCUMENT_SUFFIXES:
        supported = ", ".join(SUPPORTED_DOCUMENT_SUFFIXES)
        raise ConfigError(
            f"Unsupported document extension {resolved.suffix!r}; expected {supported}."
        )
    return resolved
