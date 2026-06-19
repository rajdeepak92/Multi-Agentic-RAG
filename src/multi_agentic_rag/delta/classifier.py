"""Simple deterministic delta classifiers."""

from __future__ import annotations


def classify_change_magnitude(old_value: str | None, new_value: str | None) -> str:
    """Classify change magnitude from normalized values.

    Args:
        old_value: Previous fact value, or `None` for additions.
        new_value: New fact value, or `None` for removals.

    Returns:
        Deterministic magnitude label such as `none`, `small`, `medium`, `large`,
        `text`, or `structural`.
    """

    if old_value == new_value:
        return "none"
    if old_value is None or new_value is None:
        return "structural"
    try:
        old_number = float(str(old_value).strip("<>= "))
        new_number = float(str(new_value).strip("<>= "))
    except ValueError:
        return "text"
    delta = abs(new_number - old_number)
    if delta == 0:
        return "none"
    if delta <= max(abs(old_number) * 0.05, 1.0):
        return "small"
    if delta <= max(abs(old_number) * 0.20, 5.0):
        return "medium"
    return "large"


def classify_risk(change_type: str, magnitude: str, fact_key: str | None) -> str:
    """Classify operational risk for a fact delta.

    Args:
        change_type: Delta type: added, removed, modified, or unchanged.
        magnitude: Magnitude label from `classify_change_magnitude`.
        fact_key: Semantic key used to identify sensitive domains.

    Returns:
        Risk label: `none`, `low`, `medium`, or `high`.
    """

    if change_type == "unchanged":
        return "none"
    if fact_key and any(term in fact_key for term in ("threshold", "protocol", "requirement")):
        return "high" if magnitude in {"large", "structural", "text"} else "medium"
    if change_type in {"added", "removed"}:
        return "medium"
    return "low"
