"""Shared data and DataFrame helpers used by every dashboard page."""

from .db import QueryCache, get_connection, run_queries, run_query
from .analytics import track_tab_click
from .scheduled_refresh import (
    current_refresh_revision,
    refresh_all_data,
    start_global_refresh_scheduler,
)
from .frames import (
    filter_frame,
    format_timestamp,
    make_financial_pivot,
    make_pivot,
    normalise_filters,
    to_numeric,
    unique_values,
)

__all__ = [
    "QueryCache",
    "current_refresh_revision",
    "filter_frame",
    "format_timestamp",
    "get_connection",
    "make_financial_pivot",
    "make_pivot",
    "normalise_filters",
    "run_queries",
    "run_query",
    "refresh_all_data",
    "start_global_refresh_scheduler",
    "to_numeric",
    "track_tab_click",
    "unique_values",
]
