"""Atomic JSON and YAML artifact writes."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def write_json_artifact(path: str | Path, payload: Any) -> Path:
    """Atomically write a JSON artifact."""

    target = Path(path)
    _atomic_write_text(
        target,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    )
    return target


def write_yaml_artifact(path: str | Path, payload: Any) -> Path:
    """Atomically write a YAML artifact."""

    target = Path(path)
    _atomic_write_text(target, yaml.safe_dump(payload, sort_keys=False, allow_unicode=False))
    return target


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(tmp_name).replace(path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
