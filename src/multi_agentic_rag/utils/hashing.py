"""Stable hashing helpers used for IDs and content lineage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_text(text: str) -> str:
    """Return the SHA-256 hex digest for text.

    Args:
        text: UTF-8 text to hash.

    Returns:
        Hex-encoded SHA-256 digest.
    """

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hex digest for a file.

    Args:
        path: File path to read in binary mode.
        chunk_size: Number of bytes to read per iteration.

    Returns:
        Hex-encoded SHA-256 digest for the file content.
    """

    digest = hashlib.sha256()
    with Path(path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    """Hash Python data deterministically using JSON serialization.

    Args:
        value: JSON-serializable value, or a value representable by `str`.

    Returns:
        Hex-encoded SHA-256 digest of the normalized JSON payload.
    """

    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(payload)


def stable_id(prefix: str, *parts: Any, length: int = 32) -> str:
    """Create a readable stable ID from typed parts.

    Args:
        prefix: Human-readable ID prefix such as `chunk` or `document`.
        *parts: Ordered identity parts used as the deterministic hash seed.
        length: Number of digest characters to keep.

    Returns:
        Stable identifier in `<prefix>_<digest>` form.
    """

    digest = stable_hash(parts)[:length]
    return f"{prefix}_{digest}"
