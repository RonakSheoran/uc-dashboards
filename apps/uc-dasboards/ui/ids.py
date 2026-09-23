"""Stable component and lineage identifiers."""
from __future__ import annotations


def component_id(page: str, kind: str, name: str) -> dict[str, str]:
    """Structured ID for new pattern-matching callbacks."""
    return {"page": page, "type": kind, "name": name}


def lineage_id(page: str, kind: str, name: str) -> str:
    """Human-readable identifier used in logs, exports and diagnostics."""
    return f"{page}.{kind}.{name}"
