"""Small dependency-free checks for the opt-in matrix cross-filter helpers."""

import importlib.util
from pathlib import Path

import pandas as pd

module_path = Path(__file__).resolve().parents[1] / "ui" / "cross_filter.py"
spec = importlib.util.spec_from_file_location("ui_cross_filter", module_path)
cross_filter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(cross_filter)
apply_matrix_selection = cross_filter.apply_matrix_selection
matrix_cell_selection = cross_filter.matrix_cell_selection
matrix_selection_style = cross_filter.matrix_selection_style


rows = [
    {"Anchor": "A", "Reattempt": 2, "Approved": 1},
    {"Anchor": "B", "Reattempt": 1, "Approved": 3},
    {"Anchor": "Total", "Reattempt": 3, "Approved": 4},
]
selection = matrix_cell_selection(
    {"row": 0, "column_id": "Reattempt"}, rows,
    row_field="Anchor", column_field="current_lead_state_n",
)
assert selection == {
    "row_field": "Anchor", "row_value": "A",
    "column_field": "current_lead_state_n", "column_value": "Reattempt",
}

detail = pd.DataFrame([
    {"Anchor": "A", "current_lead_state_n": "Reattempt", "lead_id": 1},
    {"Anchor": "A", "current_lead_state_n": "Approved", "lead_id": 2},
    {"Anchor": "B", "current_lead_state_n": "Reattempt", "lead_id": 3},
])
filtered = apply_matrix_selection(detail, selection)
assert filtered["lead_id"].tolist() == [1]
assert matrix_cell_selection(
    {"row": 2, "column_id": "Reattempt"}, rows,
    row_field="Anchor", column_field="current_lead_state_n",
) is None
style = matrix_selection_style(
    selection, row_field="Anchor", column_field="current_lead_state_n",
)
assert style[0]["if"] == {
    "filter_query": '{Anchor} = "A"', "column_id": "Reattempt",
}
assert style[0]["border"] == "2px solid #DE1414"
assert matrix_selection_style(
    selection, row_field="Anchor", column_field="lead_worked_age_bucket",
) == []
print("PASS: matrix cell selection and detail cross-filter")
