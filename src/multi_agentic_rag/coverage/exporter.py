"""Coverage export helpers."""

from __future__ import annotations

import json
from pathlib import Path

from multi_agentic_rag.models import CoverageRecord


def export_coverage_json(records: list[CoverageRecord], path: str | Path) -> Path:
    """Write coverage records as JSON."""

    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([record.model_dump(mode="json") for record in records], indent=2),
        encoding="utf-8",
    )
    return target
