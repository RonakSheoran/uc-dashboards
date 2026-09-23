"""Load validated-by-shape application JSON configuration.

The configuration is deliberately read-only at runtime. Deployments validate and
ship a complete config set, which keeps page rendering deterministic.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


@lru_cache(maxsize=None)
def load_json(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Configuration must be a JSON object: {path}")
    return value


APP_CONFIG = load_json("app.json")
THEME = load_json("theme.json")
NAVIGATION = load_json("navigation.json")
REFRESH_CONFIG = load_json("refresh.json")
TABLE_SOURCES = load_json("tables.json")["tables"]
VISUAL_LINEAGE = load_json("visual_lineage.json")["visuals"]
COLUMN_ORDERS = load_json("column_order.json")["columns"]


def theme_value(path: str, default: Any = None) -> Any:
    """Read a dotted theme key, e.g. ``colors.primary``."""
    current: Any = THEME
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def theme_css_variables() -> dict[str, str]:
    """Expose JSON theme tokens to CSS descendants of the application root."""
    return {
        "--uc-primary": str(theme_value("colors.primary", "#DC3545")),
        "--uc-primary-dark": str(theme_value("colors.primary_dark", "#B81010")),
        "--uc-secondary": str(theme_value("colors.secondary", "#4472C4")),
        "--uc-surface": str(theme_value("colors.surface", "#FFFFFF")),
        "--uc-background": str(theme_value("colors.background", "#F0F0F3")),
        "--uc-text": str(theme_value("colors.text", "#111111")),
        "--uc-muted": str(theme_value("colors.muted", "#555555")),
        "--uc-border": str(theme_value("colors.border", "#E5E7EB")),
        "--uc-font": str(theme_value("typography.family", "DM Sans, sans-serif")),
    }
