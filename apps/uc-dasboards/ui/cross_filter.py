"""Opt-in matrix-to-detail cross-filter helpers.

The helpers are deliberately callback-agnostic.  A page must explicitly wire
matrix ``active_cell`` events into a store and apply the stored selection to a
detail frame.  Nothing is registered globally, so pages that do not opt in pay
no callback or rendering cost.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import pandas as pd


def matrix_cell_selection(
    active_cell: Optional[Mapping[str, Any]],
    visible_rows: Optional[Sequence[Mapping[str, Any]]],
    *,
    row_field: str,
    column_field: str,
    total_label: str = "Total",
) -> Optional[dict[str, Any]]:
    """Translate a clicked matrix value cell into a serializable filter."""
    if not active_cell or not visible_rows:
        return None
    row_index = active_cell.get("row")
    column_id = active_cell.get("column_id")
    if not isinstance(row_index, int) or row_index < 0 or row_index >= len(visible_rows):
        return None
    if not column_id or str(column_id) == row_field or str(column_id).startswith("__uc_"):
        return None
    row_value = visible_rows[row_index].get(row_field)
    if row_value is None or str(row_value).strip().casefold() == total_label.casefold():
        return None
    if str(column_id).strip().casefold() == total_label.casefold():
        return None
    return {
        "row_field": row_field,
        "row_value": row_value,
        "column_field": column_field,
        "column_value": column_id,
    }


def apply_matrix_selection(
    frame: pd.DataFrame,
    selection: Optional[Mapping[str, Any]],
) -> pd.DataFrame:
    """Filter detail rows to the row/column cohort selected in a matrix."""
    if frame is None or frame.empty or not selection:
        return frame
    row_field = selection.get("row_field")
    column_field = selection.get("column_field")
    if row_field not in frame.columns or column_field not in frame.columns:
        return frame
    row_value = str(selection.get("row_value"))
    column_value = str(selection.get("column_value"))
    return frame[
        frame[row_field].astype(str).eq(row_value)
        & frame[column_field].astype(str).eq(column_value)
    ]


def matrix_selection_label(selection: Optional[Mapping[str, Any]]) -> str:
    """Return a compact human-readable description of a matrix selection."""
    if not selection:
        return "No matrix cell selected"
    return (
        f"{selection.get('row_field')} = {selection.get('row_value')}  |  "
        f"{selection.get('column_field')} = {selection.get('column_value')}"
    )


def matrix_selection_style(
    selection: Optional[Mapping[str, Any]],
    *,
    row_field: str,
    column_field: str,
    background_color: str = "#FDE8EA",
    border_color: str = "#DE1414",
) -> list[dict[str, Any]]:
    """Return a persistent Dash DataTable style for the selected matrix cell."""
    if not selection:
        return []
    if (
        selection.get("row_field") != row_field
        or selection.get("column_field") != column_field
    ):
        return []
    row_value = str(selection.get("row_value", ""))
    column_value = str(selection.get("column_value", ""))
    if not row_value or not column_value:
        return []
    escaped_row_value = row_value.replace("\\", "\\\\").replace('"', '\\"')
    return [{
        "if": {
            "filter_query": f'{{{row_field}}} = "{escaped_row_value}"',
            "column_id": column_value,
        },
        "backgroundColor": background_color,
        "border": f"2px solid {border_color}",
        "color": "#111111",
        "fontWeight": "700",
    }]
