"""Per-command run context and manifest handling."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from multi_agentic_rag.common_defs import (
    ARTIFACTS_DIR_NAME,
    DEBUG_DIR_NAME,
    GENERATED_DIR_NAME,
    LOGS_DIR_NAME,
    RESULTS_DIR_NAME,
    USER_STORIES_DIR_NAME,
)
from multi_agentic_rag.runtime.config_loader import RuntimeConfigResolution
from multi_agentic_rag.runtime.secrets import redact_secrets


@dataclass
class RunContext:
    """Filesystem context for one command run."""

    run_id: str
    project_root: Path
    run_dir: Path
    logs_dir: Path
    results_dir: Path
    artifacts_dir: Path
    user_story_artifacts_dir: Path
    debug_dir: Path
    log_path: Path
    manifest_path: Path
    command: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def write_manifest(self, **updates: Any) -> None:
        """Write a redacted manifest snapshot."""

        self.metadata.update(updates)
        payload = {
            "run_id": self.run_id,
            "command": self.command,
            "project_root": str(self.project_root),
            "run_dir": str(self.run_dir),
            "created_at": self.metadata.get("created_at"),
            "metadata": self.metadata,
        }
        self.manifest_path.write_text(
            json.dumps(redact_secrets(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def create_run_context(
    project_root: Path,
    *,
    command: str,
    config_resolution: RuntimeConfigResolution | None = None,
    device_plan: Any | None = None,
) -> RunContext:
    """Create the standard generated/RUN... folder layout."""

    now = datetime.now(UTC)
    run_id = f"RUN_{now.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    run_dir = project_root / GENERATED_DIR_NAME / run_id
    logs_dir = run_dir / LOGS_DIR_NAME
    results_dir = run_dir / RESULTS_DIR_NAME
    artifacts_dir = results_dir / ARTIFACTS_DIR_NAME
    user_story_artifacts_dir = artifacts_dir / USER_STORIES_DIR_NAME
    debug_dir = results_dir / DEBUG_DIR_NAME
    for path in (logs_dir, user_story_artifacts_dir, debug_dir):
        path.mkdir(parents=True, exist_ok=True)
    context = RunContext(
        run_id=run_id,
        project_root=project_root,
        run_dir=run_dir,
        logs_dir=logs_dir,
        results_dir=results_dir,
        artifacts_dir=artifacts_dir,
        user_story_artifacts_dir=user_story_artifacts_dir,
        debug_dir=debug_dir,
        log_path=logs_dir / "run.log",
        manifest_path=run_dir / "run_manifest.json",
        command=command,
        metadata={
            "created_at": now.isoformat(),
            "config": config_resolution.redacted() if config_resolution else None,
            "device_plan": _dump_device_plan(device_plan),
        },
    )
    context.write_manifest()
    return context


def _dump_device_plan(device_plan: Any | None) -> Any | None:
    if device_plan is None:
        return None
    if hasattr(device_plan, "model_dump"):
        return device_plan.model_dump(mode="json")
    if hasattr(device_plan, "__dict__"):
        return dict(device_plan.__dict__)
    return device_plan
