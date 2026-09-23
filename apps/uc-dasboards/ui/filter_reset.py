"""Reusable registration for deterministic page-local filter resets."""

from __future__ import annotations

from collections.abc import Sequence

from dash import Input, Output, callback


def register_filter_reset(button_id: str, filter_ids: Sequence[str]) -> None:
    """Register one clear button against the dropdowns present on its page."""
    targets = tuple(filter_ids)
    if not targets:
        return

    @callback(
        [Output(component_id, "value") for component_id in targets],
        Input(button_id, "n_clicks"),
        prevent_initial_call=True,
    )
    def clear_page_filters(_n_clicks):
        return [None] * len(targets)
