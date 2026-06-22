"""Secret redaction helpers for logs, manifests, and diagnostics."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "DSN")
_DSN_PASSWORD_RE = re.compile(r"((?:postgres(?:ql)?|postgresql\+asyncpg)://[^:\s/@]+):([^@\s]+)@")
_KEY_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|dsn)(['\"]?\s*[:=]\s*['\"]?)([^'\"\s,}]+)"
)


def collect_secret_values(
    environ: Mapping[str, str] | None = None,
    *,
    extra: list[str | None] | tuple[str | None, ...] = (),
) -> list[str]:
    """Collect known secret values from environment-like mappings."""

    env = environ or os.environ
    values: list[str] = []
    for name, value in env.items():
        if not value:
            continue
        if any(marker in name.upper() for marker in SECRET_ENV_MARKERS):
            values.append(value)
    for extra_value in extra:
        if extra_value:
            values.append(extra_value)
    return sorted(set(values), key=len, reverse=True)


def redact_secrets(value: Any, *, secrets: list[str] | None = None) -> Any:
    """Return a redacted copy of a scalar, list, or mapping."""

    if isinstance(value, Mapping):
        return {
            key: "***"
            if _looks_secret_key(str(key))
            else redact_secrets(item, secrets=secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, secrets=secrets) for item in value)
    if not isinstance(value, str):
        return value
    return redact_secret_text(value, secrets=secrets)


def redact_secret_text(text: str, *, secrets: list[str] | None = None) -> str:
    """Redact secret-looking values in one text string."""

    redacted = _DSN_PASSWORD_RE.sub(r"\1:***@", text)
    redacted = _KEY_VALUE_RE.sub(r"\1\2***", redacted)
    for secret in secrets or collect_secret_values():
        if not secret or len(secret) < 4:
            continue
        redacted = redacted.replace(secret, "***")
    return redacted


def _looks_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(marker in upper for marker in SECRET_ENV_MARKERS)
