"""Path normalization and run-directory helpers."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path

from multi_agentic_rag.exceptions import ConfigError


def safe_relative_path(path: str | Path, *, root: str | Path) -> Path:
    """Resolve a path and ensure it stays under the configured root."""

    resolved_root = Path(root).expanduser().resolve()
    resolved = Path(path).expanduser().resolve()
    if resolved != resolved_root and not resolved.is_relative_to(resolved_root):
        raise ConfigError(f"{resolved} must stay inside {resolved_root}.")
    return resolved


def create_run_directory(generated_dir: str | Path) -> tuple[str, Path]:
    """Create generated/runs/RUN_<timestamp>_<shortid> with standard children."""

    now = datetime.now(UTC)
    run_id = f"RUN_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    run_dir = Path(generated_dir).expanduser().resolve() / "runs" / run_id
    for child in (
        run_dir,
        run_dir / "artifacts" / "user_stories",
        run_dir / "debug",
    ):
        child.mkdir(parents=True, exist_ok=True)
    return run_id, run_dir
