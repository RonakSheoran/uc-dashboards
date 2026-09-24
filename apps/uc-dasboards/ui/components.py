"""Reusable, theme-backed Dash components.

These functions intentionally accept semantic options (variant, density,
placement) instead of arbitrary style dictionaries. This keeps every dashboard
visually consistent and makes JSON-driven pages straightforward later.
"""
from __future__ import annotations

import base64
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import MATCH, Input, Output, State, callback, dcc, html, dash_table
import dash_bootstrap_components as dbc

from .config import theme_value
from .identifiers import (
    identified_visual, next_visual_id, unwrap_identified_visual,
    visual_source_ids,
)


PRIMARY = theme_value("colors.primary", "#DC3545")
PRIMARY_DARK = theme_value("colors.primary_dark", "#B81010")
SECONDARY = theme_value("colors.secondary", "#4472C4")
SURFACE = theme_value("colors.surface", "#FFFFFF")
TEXT = theme_value("colors.text", "#111111")
MUTED = theme_value("colors.muted", "#555555")
BORDER = theme_value("colors.border", "#E5E7EB")
GRID = theme_value("colors.grid", "#F0F0F0")
FONT = theme_value("typography.family", "DM Sans, sans-serif")
CHART_COLORS = theme_value("charts.series", [PRIMARY, "#8B5CF6", "#F59E0B", "#06B6D4"])
_ROW_ORDER_KEY = "__uc_original_row_order__"


def _show_all_date_ticks(figure: go.Figure, x_title: Optional[str] = None) -> None:
    """Show every observed date/day on every Plotly date-based x-axis."""
    values = []
    seen = set()
    for trace in figure.data:
        trace_values = getattr(trace, "x", None)
        if trace_values is None:
            continue
        for value in trace_values:
            try:
                if pd.isna(value):
                    continue
            except (TypeError, ValueError):
                pass
            marker = (type(value).__name__, str(value))
            if marker not in seen:
                seen.add(marker)
                values.append(value)

    if not values:
        return

    title = str(x_title or "").casefold()
    title_is_date = any(token in title for token in ("date", "day", "month"))
    typed_dates = any(
        isinstance(value, (date, datetime, pd.Timestamp, np.datetime64))
        for value in values
    )
    string_values = [value for value in values if isinstance(value, str)]
    strings_are_dates = False
    if string_values and len(string_values) == len(values):
        date_candidates = [value for value in string_values if "-" in value or "/" in value]
        if date_candidates:
            parsed = pd.to_datetime(pd.Series(date_candidates), errors="coerce")
            strings_are_dates = parsed.notna().mean() >= 0.8

    if not (title_is_date or typed_dates or strings_are_dates):
        return

    tick_text = []
    for value in values:
        if isinstance(value, str):
            tick_text.append(value)
        elif isinstance(value, (date, datetime, pd.Timestamp, np.datetime64)):
            tick_text.append(pd.Timestamp(value).strftime("%Y-%m-%d"))
        else:
            tick_text.append(str(value))

    figure.update_xaxes(
        tickmode="array",
        tickvals=values,
        ticktext=tick_text,
        tickangle=-45,
        automargin=True,
    )


def _is_blank_sort_value(value: Any) -> bool:
    if value is None or value == "":
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _sort_value(value: Any) -> tuple[int, Any]:
    """Sort numeric-looking formatted values numerically and other values as text."""
    if isinstance(value, (int, float, np.integer, np.floating)):
        return 0, float(value)
    text = str(value).strip()
    numeric = text.replace(",", "").removesuffix("%").strip()
    try:
        return 0, float(numeric)
    except ValueError:
        return 1, text.casefold()


@callback(
    Output({"type": "ui-summary-table", "index": MATCH}, "data"),
    Input({"type": "ui-summary-table", "index": MATCH}, "sort_by"),
    State({"type": "ui-summary-table", "index": MATCH}, "data"),
    prevent_initial_call=True,
)
def _sort_summary_table(sort_by, rows):
    """Apply user sorting to detail rows while permanently pinning Total last."""
    if not rows:
        return rows
    first_column = next((key for key in rows[0] if key != _ROW_ORDER_KEY), None)
    if not first_column:
        return rows
    details = [
        dict(row) for row in rows
        if str(row.get(first_column, "")).strip().casefold() != "total"
    ]
    totals = [
        dict(row) for row in rows
        if str(row.get(first_column, "")).strip().casefold() == "total"
    ]
    if sort_by:
        # Reversed application preserves Dash's multi-column stable-sort order.
        for specification in reversed(sort_by):
            column = specification.get("column_id")
            if not column:
                continue
            populated = [row for row in details if not _is_blank_sort_value(row.get(column))]
            blanks = [row for row in details if _is_blank_sort_value(row.get(column))]
            populated.sort(
                key=lambda row: _sort_value(row.get(column)),
                reverse=specification.get("direction") == "desc",
            )
            details = populated + blanks
    else:
        details.sort(key=lambda row: row.get(_ROW_ORDER_KEY, 0))
    return details + totals


def _logo_data_uri() -> str:
    svg = '''<svg width="180" height="56" viewBox="0 0 360 112" xmlns="http://www.w3.org/2000/svg">
    <rect width="360" height="112" rx="18" fill="#DC3545"/>
    <circle cx="62" cy="56" r="38" fill="white"/>
    <text x="62" y="73" text-anchor="middle" font-size="52" fill="#DC3545" font-weight="700" font-family="Arial">उ</text>
    <text x="220" y="48" text-anchor="middle" font-size="30" fill="white" font-weight="600" font-family="Arial">udaan</text>
    <text x="220" y="83" text-anchor="middle" font-size="30" fill="white" font-weight="600" font-family="Arial">Capital</text>
    </svg>'''
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("utf-8")


LOGO_URI = _logo_data_uri()


def _id_kwargs(component_id: Any) -> dict[str, Any]:
    """Dash rejects an explicitly supplied ``id=None``; omit it instead."""
    return {"id": component_id} if component_id is not None else {}


def empty_state(message: str = "No data available for selected filters"):
    return html.Div(message, className="ui-state ui-state--empty")


def error_state(message: str):
    return html.Div(message, className="ui-state ui-state--error")


def section_title(text: str, *, variant: str = "primary"):
    color = SECONDARY if variant == "secondary" else PRIMARY
    return html.Div(text, className="ui-section-title", style={"borderLeftColor": color})


def visual_card(children, *, title: Optional[str] = None, class_name: str = ""):
    content = []
    if title:
        content.append(section_title(title))
    if isinstance(children, (list, tuple)):
        content.extend(children)
    else:
        content.append(children)
    return html.Div(content, className=f"ui-card {class_name}".strip())


def header_ui(
    title: Any,
    *,
    subtitle: Optional[str] = None,
    updated_text: Optional[str] = None,
    title_id: Optional[str] = None,
    subtitle_id: Optional[str] = None,
    badge_id: Optional[str] = None,
    logo_uri: Optional[str] = None,
):
    title_node = html.Div(title, className="ui-page-title", **_id_kwargs(title_id))
    middle = [title_node]
    if subtitle is not None or subtitle_id:
        middle.append(html.Div(subtitle or "", className="ui-page-subtitle", **_id_kwargs(subtitle_id)))
    right = html.Div(
        [html.Div("Last Update", className="ui-refresh-label"),
         html.Div(updated_text or "Not available", className="ui-refresh-value", **_id_kwargs(badge_id))],
        className="ui-refresh-badge",
    )
    return html.Div(
        [html.Img(src=logo_uri or LOGO_URI, className="ui-logo"), html.Div(middle, className="ui-page-heading"), right],
        className="ui-header",
    )


def filter_ui(
    label: str,
    component_id: Any,
    options: Iterable[Any],
    *,
    multi: bool = True,
    placeholder: str = "All",
    value: Any = None,
    variant: str = "plain",
):
    option_list = [{"label": str(o), "value": o} for o in options]
    class_name = f"ui-filter ui-filter--{variant}"
    return html.Div(
        [
            html.Label(label, className="ui-filter__label"),
            dcc.Dropdown(
                id=component_id,
                options=option_list,
                multi=multi,
                placeholder=placeholder,
                value=value,
                className="ui-filter__control",
            ),
        ],
        className=class_name,
    )


def tab_bar(
    tabs: Sequence[tuple[str, str]] | Sequence[Mapping[str, Any]],
    *,
    id_prefix: str,
    active: str,
    class_name: str = "ui-tabs",
):
    normalized = [
        (str(t["id"]), str(t["label"])) if isinstance(t, Mapping) else (str(t[0]), str(t[1]))
        for t in tabs
    ]
    buttons = [
            html.Button(
                label,
                id=f"{id_prefix}{value}",
                n_clicks=0,
                className=f"ui-tab{' active' if value == active else ''}",
            )
            for value, label in normalized
    ]
    return html.Div([
        html.Div(buttons, className="ui-tabs__buttons"),
        html.Div([
            html.Label("View", className="ui-tabs__mobile-label"),
            dcc.Dropdown(
                id=f"{id_prefix}mobile",
                options=[{"label": label, "value": value} for value, label in normalized],
                value=active,
                clearable=False,
                searchable=False,
                className="ui-tabs__mobile-select",
            ),
        ], className="ui-tabs__mobile"),
    ], className=class_name)


def link_tab_bar(
    tabs: Sequence[tuple[str, str]] | Sequence[Mapping[str, Any]],
    *,
    active: str,
    href_prefix: str = "/",
    mobile_id: str = "link-tabs-mobile",
):
    """Navigation tabs that update the URL instead of a callback-backed store."""
    normalized = [
        (str(t["id"]), str(t["label"])) if isinstance(t, Mapping) else (str(t[0]), str(t[1]))
        for t in tabs
    ]
    links = [
        dcc.Link(
            html.Button(label, className=f"ui-tab{' active' if value == active else ''}"),
            href=f"{href_prefix}{value}",
        )
        for value, label in normalized
    ]
    return html.Div([
        html.Div(links, className="ui-tabs__buttons"),
        html.Div([
            html.Label("View", className="ui-tabs__mobile-label"),
            dcc.Dropdown(
                id=mobile_id,
                options=[{"label": label, "value": value} for value, label in normalized],
                value=active,
                clearable=False,
                searchable=False,
                className="ui-tabs__mobile-select",
            ),
        ], className="ui-tabs__mobile"),
    ], className="ui-tabs")


def download_button(
    component_id: Any,
    *,
    label: str = "Download filtered",
    variant: str = "primary",
):
    return html.Button(
        [html.Span("⇩", className="ui-download__icon"), label],
        id=component_id,
        n_clicks=0,
        className=f"ui-download ui-download--{variant}",
    )


def full_export_controls(
    button_id: Any,
    download_id: Any,
    *,
    label: str = "Export all filtered rows",
    variant: str = "primary",
):
    """Render a server-side full-export trigger and its download target."""
    return html.Div(
        [
            download_button(button_id, label=label, variant=variant),
            dcc.Download(id=download_id),
        ],
        className="ui-full-export",
    )


def clear_filters_button(
    component_id: Any,
    *,
    label: str = "Clear all filters",
):
    """Render a page-local filter-reset command."""
    return html.Button(
        [
            html.Span("×", className="ui-clear-filters__icon"),
            html.Span(label, className="ui-clear-filters__label"),
        ],
        n_clicks=0,
        className="ui-clear-filters",
        title=label,
        **_id_kwargs(component_id),
    )


def kpi_card(
    label: str,
    value: Any,
    *,
    component_id: Any = None,
    track_visual: bool = False,
):
    """Render a KPI card, optionally reserving and displaying a visual ID."""
    children = [
        html.Div(label, className="ui-kpi__label"),
        html.Div(value, className="ui-kpi__value", **_id_kwargs(component_id)),
    ]
    metadata: dict[str, Any] = {}
    if track_visual:
        visual_id = next_visual_id()
        source_ids = visual_source_ids(visual_id)
        source_text = ", ".join(source_ids)
        lineage = [html.Span("Widget"), html.Code(visual_id or "")]
        if source_ids:
            lineage.extend([html.Span("Source"), html.Code(source_text)])
        children.append(
            html.Div(
                lineage,
                className="ui-kpi__lineage",
                title=(
                    f"Widget identifier {visual_id}; source {source_text}"
                    if source_text else f"Widget identifier {visual_id}"
                ),
            )
        )
        metadata = {
            "data-visual-id": visual_id or "",
            "data-visual-kind": "widget",
            "data-source-ids": source_text,
        }
    return html.Div(children, className="ui-kpi", **metadata)


def table_ui(
    data: pd.DataFrame,
    *,
    component_id: Any = None,
    columns: Optional[Sequence[str]] = None,
    page_size: Optional[int] = None,
    sortable: bool = True,
    filterable: bool = False,
    downloadable: bool = True,
    export_format: str = "xlsx",
    sticky_header: bool = True,
    max_height: Optional[int] = None,
    first_column_left: bool = True,
    total_label: str = "Total",
    show_summary: bool = True,
    variant: str = "primary",
    style_data_conditional: Optional[list[dict[str, Any]]] = None,
    style_header_conditional: Optional[list[dict[str, Any]]] = None,
):
    visual_id = next_visual_id()
    if data is None or data.empty:
        return identified_visual(
            empty_state("No rows available for the selected filters."),
            "table",
            identifier=visual_id,
        )
    display = data.copy()
    if columns:
        display = display[[c for c in columns if c in display.columns]]
    original_columns = list(display.columns)
    for col in display.columns:
        if pd.api.types.is_float_dtype(display[col]):
            display[col] = display[col].round(2)

    first_column = display.columns[0] if len(display.columns) else None
    first_col = str(first_column) if first_column is not None else ""
    if show_summary and first_col:
        existing_total = (
            display[first_column].astype(str).str.strip().str.casefold()
            == total_label.strip().casefold()
        )
        if existing_total.any():
            # Preserve page-specific totals (important for ratios/percentages),
            # but ensure the summary is the final row for the sticky footer.
            total_row = display.loc[existing_total].tail(1)
            display = pd.concat([display.loc[~existing_total], total_row], ignore_index=True)
        else:
            summary_row: dict[str, Any] = {}
            for index, column in enumerate(display.columns):
                if index == 0:
                    summary_row[column] = total_label
                elif (
                    pd.api.types.is_numeric_dtype(display[column])
                    and not pd.api.types.is_bool_dtype(display[column])
                ):
                    value = display[column].sum(min_count=1)
                    summary_row[column] = round(value, 2) if pd.notna(value) else ""
                else:
                    summary_row[column] = ""
            display = pd.concat([display, pd.DataFrame([summary_row])], ignore_index=True)
        # Summary construction must never change business-defined column order.
        display = display.reindex(columns=original_columns)

    header_color = SECONDARY if variant == "secondary" else "#F3F2F1"
    header_text = "#FFFFFF" if variant == "secondary" else TEXT
    conditional = []
    if theme_value("tables.striped", True):
        conditional.append({"if": {"row_index": "odd"}, "backgroundColor": "#FCFCFD"})
    conditional.extend(style_data_conditional or [])
    if show_summary and first_col:
        escaped_total = total_label.replace('"', '\\"')
        conditional.append({
            "if": {"filter_query": f'{{{first_col}}} = "{escaped_total}"'},
            "fontWeight": "700", "backgroundColor": "#F9F9F9",
            "borderTop": f"2px solid {PRIMARY}",
        })

    records = display.to_dict("records")
    for row_number, record in enumerate(records):
        record[_ROW_ORDER_KEY] = row_number
    table_key = str(component_id or visual_id or f"table-{id(display)}")
    table_component_id = (
        {"type": "ui-summary-table", "index": table_key}
        if sortable and show_summary and first_col else component_id
    )
    table = dash_table.DataTable(
        data=records,
        columns=[{"name": str(c), "id": str(c)} for c in display.columns],
        page_action="none",
        sort_action="custom" if sortable and show_summary and first_col else "native" if sortable else "none",
        sort_mode="multi",
        sort_by=[],
        filter_action="native" if filterable else "none",
        export_format=export_format if downloadable else "none",
        export_headers="ids",
        fixed_rows={"headers": True} if sticky_header else None,
        style_table={
            "overflowX": "auto", "overflowY": "auto",
            "maxHeight": f"{max_height or int(theme_value('tables.max_height', 400))}px",
            "border": f"1px solid {BORDER}", "borderRadius": "6px",
        },
        style_header={
            "backgroundColor": header_color, "color": header_text, "fontWeight": "600",
            "fontSize": "11px", "textAlign": "center", "padding": "6px 8px",
            "borderBottom": f"2px solid {PRIMARY}",
        },
        style_header_conditional=style_header_conditional or [],
        style_cell={
            "fontSize": "11px", "padding": "5px 8px", "textAlign": "right",
            "minWidth": "80px", "whiteSpace": "nowrap", "fontFamily": FONT,
            "borderRight": f"1px solid {BORDER}",
        },
        style_cell_conditional=[{
            "if": {"column_id": first_col}, "textAlign": "left", "fontWeight": "500", "minWidth": "150px",
        }] if first_column_left and first_col else [],
        style_data_conditional=conditional,
        css=[{
            "selector": "tbody tr:last-child td",
            "rule": (
                "position: sticky; bottom: 0; z-index: 4; "
                "background-color: #F9F9F9; font-weight: 700; "
                f"border-top: 2px solid {PRIMARY};"
            ),
        }] if show_summary else [],
        **_id_kwargs(table_component_id),
    )
    return identified_visual(table, "table", identifier=visual_id)


def matrix_table(
    data: pd.DataFrame,
    component_id: Any,
    *,
    highlight_first_column: bool = False,
    variant: str = "primary",
):
    component = table_ui(
        data,
        component_id=component_id,
        page_size=max(len(data), 1) if data is not None else None,
        export_format="csv",
        variant=variant,
    )
    table = unwrap_identified_visual(component)
    if highlight_first_column and isinstance(table, dash_table.DataTable) and len(data.columns):
        table.style_cell_conditional = list(table.style_cell_conditional or []) + [{
            "if": {"column_id": str(data.columns[0])}, "backgroundColor": "#FFD966",
        }]
    return component


def apply_figure_theme(
    figure: go.Figure,
    *,
    title: Optional[str] = None,
    height: Optional[int] = None,
    legend: str = "bottom",
    percent: bool = False,
    x_title: Optional[str] = None,
    y_title: Optional[str] = None,
) -> go.Figure:
    legend_config = {"orientation": "h", "yanchor": "top", "y": -0.18, "xanchor": "center", "x": 0.5}
    if legend == "right":
        legend_config = {"orientation": "v", "x": 1.02, "y": 1}
    figure.update_layout(
        title={"text": title or "", "font": {"size": 13, "color": TEXT}, "x": 0, "xanchor": "left"},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=SURFACE,
        height=height or int(theme_value("charts.height", 320)),
        margin={"l": 50, "r": 20, "t": 40 if title else 15, "b": 45},
        font={"family": FONT, "size": 11, "color": MUTED},
        legend=legend_config, hovermode="x unified",
        hoverlabel={"bgcolor": "white", "bordercolor": BORDER, "font": {"color": TEXT}},
    )
    figure.update_xaxes(gridcolor=GRID, zeroline=False, title_text=x_title)
    figure.update_yaxes(gridcolor=GRID, zeroline=False, title_text=y_title, ticksuffix="%" if percent else "")
    _show_all_date_ticks(figure, x_title=x_title)
    return figure


def line_chart(
    data: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    color: Optional[str] = None,
    pct: bool = False,
    *,
    component_id: Any = None,
):
    fig = go.Figure()
    if data is not None and not data.empty and x in data.columns and y in data.columns:
        values = pd.to_numeric(data[y], errors="coerce").round(2)
        fig.add_trace(go.Scatter(
            x=data[x], y=values, mode="lines", name=title,
            line={"color": color or CHART_COLORS[0], "width": theme_value("charts.line_width", 2.5)},
            hovertemplate="%{x}<br>%{y:.2f}" + ("%" if pct else "") + "<extra></extra>",
        ))
    apply_figure_theme(fig, title=title, percent=pct)
    return identified_visual(
        dcc.Graph(figure=fig, config={"displayModeBar": False}, **_id_kwargs(component_id)),
        "chart",
    )


def multi_line_chart(
    data: pd.DataFrame,
    x: str,
    y_cols: Sequence[str],
    title: str,
    labels: Optional[Sequence[str]] = None,
    colors: Optional[Sequence[str]] = None,
    *,
    component_id: Any = None,
    smooth: bool = False,
):
    fig = go.Figure()
    palette = list(colors or CHART_COLORS)
    names = list(labels or y_cols)
    if data is not None and not data.empty and x in data.columns:
        for index, column in enumerate(y_cols):
            if column not in data.columns:
                continue
            values = pd.to_numeric(data[column], errors="coerce").where(lambda s: s.notna(), None)
            line = {"color": palette[index % len(palette)], "width": theme_value("charts.line_width", 2.5)}
            if smooth:
                line.update({"shape": "spline", "smoothing": 1.0})
            fig.add_trace(go.Scatter(
                x=data[x], y=values, mode="lines", name=names[index] if index < len(names) else column,
                line=line, connectgaps=False, hovertemplate="%{x}<br>%{y:.2f}<extra></extra>",
            ))
    apply_figure_theme(fig, title=title, x_title=x)
    return identified_visual(
        dcc.Graph(figure=fig, config={"displayModeBar": False}, **_id_kwargs(component_id)),
        "chart",
    )


def chart_ui(
    data: pd.DataFrame,
    *,
    component_id: Any,
    chart_type: str,
    x: str,
    y: str | Sequence[str],
    title: str,
    labels: Optional[Sequence[str]] = None,
    colors: Optional[Sequence[str]] = None,
    percent: bool = False,
    stacked: bool = False,
):
    """Generic chart entry point used by configuration-driven pages."""
    y_columns = [y] if isinstance(y, str) else list(y)
    palette = list(colors or CHART_COLORS)
    names = list(labels or y_columns)
    fig = go.Figure()
    if data is not None and not data.empty and x in data.columns:
        for index, column in enumerate(y_columns):
            if column not in data.columns:
                continue
            common = {
                "x": data[x], "y": pd.to_numeric(data[column], errors="coerce"),
                "name": names[index] if index < len(names) else column,
            }
            color = palette[index % len(palette)]
            if chart_type == "line":
                trace = go.Scatter(**common, mode="lines", line={"color": color, "width": theme_value("charts.line_width", 2.5)})
            elif chart_type == "area":
                trace = go.Scatter(**common, mode="lines", fill="tozeroy", line={"color": color})
            elif chart_type in {"bar", "column"}:
                trace = go.Bar(**common, marker_color=color)
            else:
                raise ValueError(f"Unsupported chart type: {chart_type}")
            fig.add_trace(trace)
    if stacked and chart_type in {"bar", "column"}:
        fig.update_layout(barmode="stack")
    apply_figure_theme(fig, title=title, percent=percent)
    return identified_visual(
        dcc.Graph(figure=fig, config={"displayModeBar": False}, **_id_kwargs(component_id)),
        "chart",
    )
