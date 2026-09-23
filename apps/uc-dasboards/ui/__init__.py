"""Shared UI primitives for every dashboard in the application."""

from .config import (
    APP_CONFIG, COLUMN_ORDERS, NAVIGATION, REFRESH_CONFIG, TABLE_SOURCES, THEME,
    VISUAL_LINEAGE, theme_value, theme_css_variables,
)
from .components import (
    apply_figure_theme,
    chart_ui,
    clear_filters_button,
    download_button,
    empty_state,
    error_state,
    filter_ui,
    full_export_controls,
    header_ui,
    kpi_card,
    link_tab_bar,
    line_chart,
    matrix_table,
    multi_line_chart,
    section_title,
    tab_bar,
    table_ui,
    visual_card,
)
from .ids import component_id, lineage_id
from .identifiers import identified_visual, visual_scope, with_visual_scope
from .filter_reset import register_filter_reset
from .cross_filter import (
    apply_matrix_selection,
    matrix_cell_selection,
    matrix_selection_label,
    matrix_selection_style,
)

__all__ = [
    "APP_CONFIG", "COLUMN_ORDERS", "NAVIGATION", "REFRESH_CONFIG", "TABLE_SOURCES", "THEME",
    "VISUAL_LINEAGE", "theme_value", "theme_css_variables",
    "apply_figure_theme", "chart_ui", "clear_filters_button", "download_button", "empty_state", "error_state",
    "filter_ui", "full_export_controls", "header_ui", "kpi_card", "link_tab_bar", "line_chart", "matrix_table",
    "multi_line_chart", "section_title", "tab_bar", "table_ui", "visual_card",
    "component_id", "lineage_id", "identified_visual", "visual_scope", "with_visual_scope",
    "register_filter_reset",
    "apply_matrix_selection", "matrix_cell_selection", "matrix_selection_label", "matrix_selection_style",
]
