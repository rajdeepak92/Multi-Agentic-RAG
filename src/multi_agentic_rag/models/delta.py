"""Version delta models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeltaRecord(BaseModel):
    """Deterministic change record between document versions."""

    delta_id: str
    system_name: str
    from_version: str
    to_version: str
    fact_key: str | None = None
    change_type: str
    change_magnitude: str
    old_value: str | None = None
    new_value: str | None = None
    affected_requirement_id: str | None = None
    risk_level: str
    evidence: list[str] = Field(default_factory=list)
