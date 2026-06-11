"""Rule-based delta magnitude and risk classification."""

from __future__ import annotations


def classify_change_magnitude(old_value: str | None, new_value: str | None) -> str:
    """Classify a deterministic value change."""

    if old_value is None or new_value is None:
        return "major"
    try:
        old_number = float(old_value)
        new_number = float(new_value)
    except (TypeError, ValueError):
        return "minor" if old_value == new_value else "major"
    if old_number == 0:
        return "major"
    ratio = abs(new_number - old_number) / abs(old_number)
    if ratio >= 0.2:
        return "major"
    if ratio >= 0.05:
        return "moderate"
    return "minor"


def classify_risk(change_type: str, change_magnitude: str, fact_key: str) -> str:
    """Assign a conservative risk level for engineering deltas."""

    if change_type in {"removed", "added"}:
        return "high"
    if fact_key.startswith("threshold:") and change_magnitude in {"major", "moderate"}:
        return "high"
    if change_magnitude == "minor":
        return "low"
    return "medium"
