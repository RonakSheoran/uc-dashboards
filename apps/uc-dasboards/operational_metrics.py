"""Operational Metrics dashboard module for the merged uC Dashboards app."""
import os
import sys
import threading
from functools import partial
from typing import Dict, List, Optional

import pandas as pd
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, callback, ctx, no_update
from ui import (
    COLUMN_ORDERS, NAVIGATION, theme_value, empty_state as ui_empty_state,
    kpi_card as ui_kpi_card, section_title as ui_section_title,
    filter_ui, table_ui, tab_bar, header_ui, apply_figure_theme,
    clear_filters_button, full_export_controls, identified_visual,
    register_filter_reset, visual_scope,
    apply_matrix_selection, matrix_cell_selection, matrix_selection_label,
    matrix_selection_style,
)
from shared import (
    QueryCache, format_timestamp, make_pivot as make_pivot_frame, run_query,
    track_tab_click,
    to_numeric as shared_to_numeric,
)

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "e6b3b3d8399e5edb")
SCHEMA = os.getenv("OPS_SCHEMA", "hive_metastore.probes")
CACHE_TTL_SEC = int(os.getenv("OPS_CACHE_TTL_SEC", "1800"))

TAB_NAMES = [
    (page["id"], page["label"])
    for page in sorted(NAVIGATION["subpages"]["operations"], key=lambda item: item.get("order", 0))
]

RED = theme_value("colors.primary", "#DE1414")
DARK = "#24292F"
TEXT = theme_value("colors.text", "#374151")
MUTED = theme_value("colors.muted", "#6B7280")
BORDER = theme_value("colors.border", "#E5E7EB")
BG = theme_value("colors.page_background", "#F8FAFC")
CARD_BG = theme_value("colors.surface", "#FFFFFF")
# Match AUM Dashboard palette: M0=light blue, M-1=orange, M-2=purple, M-3=red
SERIES_COLORS = ["#5B9BD5", "#ED7D31", "#7030A0", "#FF0000"]
SERIES_NAMES = ["M0", "M-1", "M-2", "M-3"]

_query_cache = QueryCache(CACHE_TTL_SEC)
_refresh_lock = threading.Lock()
to_numeric = partial(shared_to_numeric, copy=True)


def get_table(table_name: str) -> pd.DataFrame:
    """Return cached DataFrame. No .copy() — callers must not mutate in-place."""
    return _query_cache.get(
        table_name,
        lambda: run_query(
            f"SELECT * FROM {SCHEMA}.{table_name}",
            context=f"operations:{table_name}",
        ),
    )


def pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def apply_filters(df: pd.DataFrame, filters: Dict[str, List[str]], alias_map: Dict[str, List[str]]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    # Only copy if we actually filter; boolean indexing already returns a new frame.
    active = {k: v for k, v in filters.items() if v}
    if not active:
        return df
    out = df
    for key, vals in active.items():
        col = pick_col(out, alias_map.get(key, [key]))
        if col:
            val_set = set(str(v) for v in vals)
            out = out[out[col].astype(str).isin(val_set)]
    return out


def option_values(dfs: List[pd.DataFrame], candidates: List[str]) -> List[str]:
    values = set()
    for df in dfs:
        if df is None or df.empty:
            continue
        col = pick_col(df, candidates)
        if col:
            vals = df[col].dropna().astype(str).tolist()
            values.update([v for v in vals if v and v.lower() != "nan"])
    return sorted(values)


def latest_refresh_text() -> str:
    candidates = []
    for table in [
        "ops_metrics_activation_dashboard_pfo47z",
        "sales_funnel_summary_fsep66",
        "lead_stock_uc_ipyaib",
        "rejection_tracking_kh32o2",
    ]:
        df = get_table(table)
        if df.empty:
            continue
        for col in ["latest_updated_at", "refresh_time", "latest_app_state_change_date"]:
            if col in df.columns:
                series = pd.to_datetime(df[col], errors="coerce").dropna()
                if not series.empty:
                    candidates.append(series.max())
    if not candidates:
        return f"Source schema: {SCHEMA}"
    return format_timestamp(max(candidates))


def empty_state(message: str):
    return ui_empty_state(message)


def metric_card(label: str, value: str):
    return dbc.Col(ui_kpi_card(label, value), md=3, sm=6, xs=12)


def section_title(text: str):
    return ui_section_title(text)


def make_dropdown(label: str, comp_id: str, options: List[str]):
    return filter_ui(label, comp_id, options, multi=True)


def make_table(df: pd.DataFrame, page_size: int = 12, *, downloadable: bool = True):
    return table_ui(
        df, page_size=page_size, filterable=True,
        export_format="xlsx", downloadable=downloadable,
    )


def pivot_view(df: pd.DataFrame, rows: str, values: str, columns: Optional[str] = None, aggfunc: str = "sum"):
    pv = make_pivot_frame(
        df, rows=rows, columns=columns, values=values, aggfunc=aggfunc,
        column_order=COLUMN_ORDERS.get(columns, []),
    )
    if pv.empty:
        return identified_visual(empty_state("No data available for this view."), "table")
    return make_table(pv, page_size=15)


def mom_figure(df: pd.DataFrame, x_col: str, series_cols: List[str], title: str) -> go.Figure:
    """Line chart matching AUM Dashboard style. Current month line stops at last real data point."""
    fig = go.Figure()
    if df is None or df.empty or x_col not in df.columns:
        fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(title=title, template="plotly_white", height=320)
        return fig
    agg_cols = [c for c in series_cols if c in df.columns]
    if not agg_cols:
        fig.add_annotation(text="No data", x=0.5, y=0.5, showarrow=False)
        fig.update_layout(title=title, template="plotly_white", height=320)
        return fig
    work = df[[x_col] + agg_cols].copy()
    for c in agg_cols:
        work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0)
    work[x_col] = pd.to_numeric(work[x_col], errors="ignore")
    work = work.groupby(x_col, dropna=False)[agg_cols].sum().reset_index().sort_values(x_col)
    for i, c in enumerate(agg_cols):
        series = work[[x_col, c]].copy()
        if i == 0:
            # Current month: truncate beyond last non-zero value
            nonzero = series[series[c] > 0]
            if not nonzero.empty:
                max_x = nonzero[x_col].max()
                series = series[series[x_col] <= max_x]
            else:
                continue
        else:
            # Past months: drop trailing zeros (month may not have 31 days)
            while len(series) > 1 and series.iloc[-1][c] == 0:
                series = series.iloc[:-1]
        fig.add_trace(go.Scatter(
            x=series[x_col], y=series[c],
            mode="lines",
            name=SERIES_NAMES[i] if i < len(SERIES_NAMES) else c,
            line={"color": SERIES_COLORS[i % len(SERIES_COLORS)], "width": 2.5},
        ))
    return apply_figure_theme(fig, x_title="DayOfMonth")


_DEFAULT_FILTER_ALIASES = {
    "team": ["Team", "team_flag", "sales_team"],
    "reporting_manager": ["reporting_manager"],
    "officer": ["officer", "sales_officer", "visited_by"],
    "anchor_name": ["anchor_name", "Anchor"],
    "application_purpose": ["application_purpose"],
    "lead_bd": ["lead_BD", "lead_bd"],
    "employee_status": ["employee_status"],
    "visited_by": ["visited_by", "officer"],
    "sprint": ["sprint"],
    "lead_sourced_by": ["lead_sourced_by"],
    "lead_source_tag": ["lead_source_tag"],
    "lead_upload_month": ["lead_upload_month"],
    "action_month": ["action_month"],
    "application_created_month": ["application_created_month"],
    "current_lead_state": ["current_lead_state_n"],
    "lead_recency_flag": ["lead_recency_flag"],
    "current_application_state": ["current_application_state"],
    "app_state_age": ["app_state_age"],
    "uw_rejected_tag": ["uw_rejected_tag"],
    "ts_generated": ["TERM_SHEET_GENERATED_TAG"],
    "bre_rejection_tag": ["BRE_rejection_tag"],
    "uw_decision_poc": ["uw_decision_poc"],
    "sales_manager": ["sales_manager"],
    "sales_team": ["sales_team"],
}


def filter_table(
    df: pd.DataFrame,
    filters: Dict[str, List[str]],
    alias_overrides: Optional[Dict[str, List[str]]] = None,
) -> pd.DataFrame:
    """Apply logical page slicers to the physical columns of one source table."""
    aliases = dict(_DEFAULT_FILTER_ALIASES)
    if alias_overrides:
        aliases.update(alias_overrides)
    return apply_filters(df, filters, aliases)


def render_onboarding(filters: Dict[str, List[str]]):
    """Matches PBI Onboarding(MOM view): 6 line charts, no KPI cards."""
    activation = filter_table(get_table("ops_metrics_activation_dashboard_pfo47z"), filters)
    leads = filter_table(get_table("ops_metrics_lead_details_gppgs3"), filters)
    anchor_visits = filter_table(get_table("anchor_poc_visits_pbi_f6m2q6"), filters)

    if activation.empty and leads.empty and anchor_visits.empty:
        return empty_state(f"No operational metrics data found. Verify schema {SCHEMA} and warehouse access.")

    activation = to_numeric(activation, [
        "M_App_count", "M_1_App_count", "M_2_App_count", "M_3_App_count",
        "M_risk_ops_logins_done_count", "M_1_risk_ops_logins_done_count", "M_2_risk_ops_logins_done_count", "M_3_risk_ops_logins_done_count",
        "M_approvals_donee_count", "M_1_approvals_done_count", "M_2_approvals_done_count", "M_3_approvals_done_count",
        "M_activations_done_count", "M_1_activations_done_count", "M_2_activations_done_count", "M_3_activations_done_count",
    ])
    leads = to_numeric(leads, ["M_lead_count", "M_1_lead_count", "M_2_lead_count", "M_3_lead_count"])
    anchor_visits = to_numeric(anchor_visits, ["M_anchor_poc_visit_count", "M_1_anchor_poc_visit_count", "M_2_anchor_poc_visit_count", "M_3_anchor_poc_visit_count"])

    def _chart(df, cols, title):
        return html.Div([
            section_title(title),
            identified_visual(
                dcc.Graph(figure=mom_figure(df, "day_base", cols, title), config={"displayModeBar": False}),
                "chart",
            ),
        ], style={"background": CARD_BG, "borderRadius": "6px", "padding": "12px", "border": f"1px solid {BORDER}", "marginBottom": "12px"})

    # Visual 4.1.1 | chart | f6m2q6 | Anchor POC visits
    # Visual 4.1.2 | chart | gppgs3 | Total leads uploaded
    # Visual 4.1.3 | chart | pfo47z | Applications created
    # Visual 4.1.4 | chart | pfo47z | Risk-Ops logins
    # Visual 4.1.5 | chart | pfo47z | Approvals
    # Visual 4.1.6 | chart | pfo47z | Activations
    return html.Div([
        dbc.Row([
            dbc.Col(_chart(anchor_visits, ["M_anchor_poc_visit_count", "M_1_anchor_poc_visit_count", "M_2_anchor_poc_visit_count", "M_3_anchor_poc_visit_count"], "#Anchor_Poc_Visits"), md=6),
            dbc.Col(_chart(leads, ["M_lead_count", "M_1_lead_count", "M_2_lead_count", "M_3_lead_count"], "#Total Leads Uploaded"), md=6),
        ], className="g-3"),
        dbc.Row([
            dbc.Col(_chart(activation, ["M_App_count", "M_1_App_count", "M_2_App_count", "M_3_App_count"], "#Total Applications Created"), md=6),
            dbc.Col(_chart(activation, ["M_risk_ops_logins_done_count", "M_1_risk_ops_logins_done_count", "M_2_risk_ops_logins_done_count", "M_3_risk_ops_logins_done_count"], "#Total Risk-Ops login done"), md=6),
        ], className="g-3"),
        dbc.Row([
            dbc.Col(_chart(activation, ["M_approvals_donee_count", "M_1_approvals_done_count", "M_2_approvals_done_count", "M_3_approvals_done_count"], "#Total Approvals done"), md=6),
            dbc.Col(_chart(activation, ["M_activations_done_count", "M_1_activations_done_count", "M_2_activations_done_count", "M_3_activations_done_count"], "#Total Activations done"), md=6),
        ], className="g-3"),
    ])


def month_summary(df: pd.DataFrame, month_col: str, metric_cols: List[str]) -> pd.DataFrame:
    if df.empty or month_col not in df.columns:
        return pd.DataFrame()
    keep = [c for c in metric_cols if c in df.columns]
    if not keep:
        return pd.DataFrame()
    work = to_numeric(df, keep)
    out = work.groupby(month_col, dropna=False)[keep].sum().reset_index()
    return out.sort_values(month_col)


def render_flow_summary(filters: Dict[str, List[str]]):
    funnel = filter_table(
        get_table("sales_funnel_summary_fsep66"), filters,
        {"lead_upload_month": ["month"], "action_month": []},
    )
    flow = filter_table(
        get_table("sales_flow_summary_euwwlz"), filters,
        {"lead_upload_month": [], "action_month": ["month"]},
    )
    funnel_month = month_summary(funnel, "month", ["lead_uploaded", "app_created", "risk_login_done", "approved", "activated", "drawdown_done", "risk_login_rejected", "gating_rejection", "total_rejected", "total_cancelled"])
    flow_month = month_summary(flow, "month", ["leads_uploaded", "apps_created", "risk_login_done", "approval_done", "activation_done", "drawdown_done", "risk_login_rejected", "gating_rejection_done", "total_rejected", "total_cancelled"])

    # Visual 4.2.1 | table | fsep66 | Sales funnel summary
    # Visual 4.2.2 | table | euwwlz | Sales flow summary
    return html.Div([
        section_title("Sales funnel summary by month"),
        make_table(funnel_month, page_size=10),
        html.Div(style={"height": "18px"}),
        section_title("Sales flow summary by month"),
        make_table(flow_month, page_size=10),
    ])


def render_anchor_performance(filters: Dict[str, List[str]]):
    funnel = filter_table(
        get_table("sales_funnel_summary_fsep66"), filters,
        {"lead_upload_month": ["month"], "action_month": []},
    )
    flow = filter_table(
        get_table("sales_flow_summary_euwwlz"), filters,
        {"lead_upload_month": [], "action_month": ["month"]},
    )
    funnel_anchor = month_summary(funnel.rename(columns={"anchor_name": "group_key"}), "group_key", ["lead_uploaded", "app_created", "risk_login_done", "approved", "activated", "drawdown_done"])
    flow_anchor = month_summary(flow.rename(columns={"anchor_name": "group_key"}), "group_key", ["leads_uploaded", "apps_created", "risk_login_done", "approval_done", "activation_done", "drawdown_done"])
    if not funnel_anchor.empty:
        funnel_anchor = funnel_anchor.rename(columns={"group_key": "anchor_name"})
    if not flow_anchor.empty:
        flow_anchor = flow_anchor.rename(columns={"group_key": "anchor_name"})

    # Visual 4.3.1 | table | fsep66 | Anchor funnel performance
    # Visual 4.3.2 | table | euwwlz | Anchor flow performance
    return html.Div([
        section_title("Anchor performance from funnel summary"),
        make_table(funnel_anchor, page_size=12),
        html.Div(style={"height": "18px"}),
        section_title("Anchor performance from flow summary"),
        make_table(flow_anchor, page_size=12),
    ])


LEAD_DETAIL_COLUMNS = [
    "lead_id", "Anchor", "lead_name", "current_lead_state_n", "officer",
    "reporting_manager", "lead_source_tag", "lead_recency_flag", "lead_age",
    "lead_worked_age", "lead_worked_age_bucket", "comment", "secondaryDisposition",
]
APP_DETAIL_COLUMNS = [
    "credit_application_id", "anchor_name", "borrower_name",
    "current_application_state", "application_created_date",
    "latest_app_state_change_date", "officer", "reporting_manager", "new_value",
    "app_state_age", "app_state_age_bucket", "lead_BD", "Team",
]


def _state_matrix(
    frame: pd.DataFrame,
    *,
    rows: str,
    columns: str,
    values: str,
    component_key: str,
    selection=None,
):
    """Build an explicitly selectable matrix for the Current State page."""
    pivot = make_pivot_frame(
        frame, rows=rows, columns=columns, values=values, aggfunc="count",
        column_order=COLUMN_ORDERS.get(columns, []),
    )
    if pivot.empty:
        return identified_visual(empty_state("No data available for this view."), "table")
    return table_ui(
        pivot,
        component_id=component_key,
        page_size=15,
        filterable=True,
        export_format="xlsx",
        style_data_conditional=matrix_selection_style(
            selection, row_field=rows, column_field=columns,
        ),
    )


def render_current_state_views(
    lead_filters: Dict[str, List[str]],
    app_filters: Dict[str, List[str]],
    lead_selection=None,
    app_selection=None,
):
    """Return the six Current State visuals in their required business order."""
    leads = filter_table(get_table("lead_stock_uc_ipyaib"), lead_filters)
    apps = filter_table(get_table("app_stock_uc_fvx6ys"), app_filters)
    selected_leads = apply_matrix_selection(leads, lead_selection)
    selected_apps = apply_matrix_selection(apps, app_selection)

    lead_detail_cols = [column for column in LEAD_DETAIL_COLUMNS if column in selected_leads.columns]
    app_detail_cols = [column for column in APP_DETAIL_COLUMNS if column in selected_apps.columns]

    # Visual 4.4.1 | table | ipyaib | Lead stock by state
    lead_state = _state_matrix(
        leads, rows="Anchor", columns="current_lead_state_n", values="lead_id",
        component_key="ops-state-lead-state-matrix", selection=lead_selection,
    )
    # Visual 4.4.2 | table | ipyaib | Lead stock by age bucket
    lead_age = _state_matrix(
        leads, rows="Anchor", columns="lead_worked_age_bucket", values="lead_id",
        component_key="ops-state-lead-age-matrix", selection=lead_selection,
    )
    # Visual 4.4.3 | table | ipyaib | Lead details
    lead_detail = make_table(
        selected_leads[lead_detail_cols].head(200) if lead_detail_cols else pd.DataFrame(),
        page_size=10, downloadable=False,
    )
    # Visual 4.4.4 | table | fvx6ys | Application stock by state
    app_state = _state_matrix(
        apps, rows="anchor_name", columns="current_application_state",
        values="credit_application_id", component_key="ops-state-app-state-matrix",
        selection=app_selection,
    )
    # Visual 4.4.5 | table | fvx6ys | Application stock by age bucket
    app_age = _state_matrix(
        apps, rows="anchor_name", columns="app_state_age_bucket",
        values="credit_application_id", component_key="ops-state-app-age-matrix",
        selection=app_selection,
    )
    # Visual 4.4.6 | table | fvx6ys | Application details
    app_detail = make_table(
        selected_apps[app_detail_cols].head(200) if app_detail_cols else pd.DataFrame(),
        page_size=10, downloadable=False,
    )
    return lead_state, lead_age, lead_detail, app_state, app_age, app_detail


def render_lead_bd_performance(filters: Dict[str, List[str]]):
    funnel = filter_table(
        get_table("sales_funnel_summary_fsep66"), filters,
        {"lead_upload_month": ["month"], "action_month": []},
    )
    flow = filter_table(
        get_table("sales_flow_summary_euwwlz"), filters,
        {"lead_upload_month": [], "action_month": ["month"]},
    )
    funnel_bd = month_summary(funnel.rename(columns={"lead_bd": "group_key"}), "group_key", ["lead_uploaded", "app_created", "risk_login_done", "approved", "activated", "drawdown_done"])
    flow_bd = month_summary(flow.rename(columns={"lead_bd": "group_key"}), "group_key", ["leads_uploaded", "apps_created", "risk_login_done", "approval_done", "activation_done", "drawdown_done"])
    if not funnel_bd.empty:
        funnel_bd = funnel_bd.rename(columns={"group_key": "lead_bd"})
    if not flow_bd.empty:
        flow_bd = flow_bd.rename(columns={"group_key": "lead_bd"})
    # Visual 4.5.1 | table | fsep66 | Lead-BD funnel performance
    # Visual 4.5.2 | table | euwwlz | Lead-BD flow performance
    return html.Div([
        section_title("Lead_BD performance from funnel summary"),
        make_table(funnel_bd, page_size=12),
        html.Div(style={"height": "18px"}),
        section_title("Lead_BD performance from flow summary"),
        make_table(flow_bd, page_size=12),
    ])


def render_rejection_cause(filters: Dict[str, List[str]]):
    rej = filter_table(get_table("rejection_tracking_kh32o2"), filters)
    rej = to_numeric(rej, ["#rejections", "Rejection%."])

    total_apps = int(rej["credit_application_id"].nunique()) if "credit_application_id" in rej.columns else 0
    total_rejections = int(rej["#rejections"].sum()) if "#rejections" in rej.columns else len(rej)
    avg_rej_pct = rej["Rejection%."].mean() if "Rejection%." in rej.columns and not rej.empty else 0
    anchors = int(rej["anchor_name"].nunique()) if "anchor_name" in rej.columns else 0

    cards = dbc.Row([
        metric_card("Applications", f"{total_apps:,}"),
        metric_card("Rejections", f"{total_rejections:,}"),
        metric_card("Avg rejection %", f"{avg_rej_pct:.2f}"),
        metric_card("Anchors", f"{anchors:,}"),
    ], className="g-3 mb-3")

    # Visual 4.6.1 | table | kh32o2 | Rejections by UW POC
    # Visual 4.6.2 | table | kh32o2 | Rejections by anchor
    # Visual 4.6.3 | table | kh32o2 | Rejection details
    return html.Div([
        cards,
        section_title("Rejections by UW decision POC and month"),
        pivot_view(rej, rows="uw_decision_poc", columns="application_created_month", values="#rejections", aggfunc="sum"),
        html.Div(style={"height": "18px"}),
        section_title("Rejections by anchor and month"),
        pivot_view(rej, rows="anchor_name", columns="application_created_month", values="#rejections", aggfunc="sum"),
        html.Div(style={"height": "18px"}),
        section_title("Rejection detail"),
        full_export_controls("ops-export-rejections-all", "ops-download-rejections-all"),
        make_table(rej.head(250), page_size=12, downloadable=False),
    ])


# ---------------------------------------------------------------------------
# Module-level startup: load all data + build filter options ONCE.
# Mirrors the pattern in aum_dashboard.py so layout() costs nothing.
# ---------------------------------------------------------------------------
_ALL_TABLES = [
    "ops_metrics_activation_dashboard_pfo47z",
    "ops_metrics_lead_details_gppgs3",
    "anchor_poc_visits_pbi_f6m2q6",
    "sales_funnel_summary_fsep66",
    "sales_flow_summary_euwwlz",
    "lead_stock_uc_ipyaib",
    "app_stock_uc_fvx6ys",
    "rejection_tracking_kh32o2",
    "bridge_table_slicers_oatmop",
    "bridge_table_leadbd_nonzwp",
]

print("[operational_metrics] Pre-loading data...", file=sys.stderr)
for _t in _ALL_TABLES:
    try:
        get_table(_t)
    except Exception as _e:
        print(f"[operational_metrics] Warning: could not pre-load {_t}: {_e}", file=sys.stderr)
print("[operational_metrics] Data pre-load complete.", file=sys.stderr)


def _build_filter_options() -> Dict[str, List[str]]:
    # Slicer fields are spread across the page datasets.  Build each business
    # slicer independently: fields such as action_month and lead_upload_month
    # are not interchangeable and must never share one generic "month" list.
    base_tables = [get_table(table_name) for table_name in _ALL_TABLES]
    return {
        "team": option_values(base_tables, ["team_flag", "Team", "sales_team"]),
        "reporting_manager": option_values(base_tables, ["reporting_manager"]),
        "officer": option_values(base_tables, ["officer", "sales_officer", "visited_by"]),
        "application_purpose": option_values(base_tables, ["application_purpose"]),
        "lead_bd": option_values(base_tables, ["lead_BD", "lead_bd"]),
        "anchor_name": option_values(base_tables, ["anchor_name", "Anchor"]),
        "lead_source_tag": option_values(base_tables, ["lead_source_tag"]),
        "lead_sourced_by": option_values(base_tables, ["lead_sourced_by"]),
        "sprint": option_values(base_tables, ["sprint"]),
        "month": option_values(base_tables, ["month"]),
        "lead_upload_month": sorted(set(
            option_values(base_tables, ["lead_upload_month"])
            + option_values([get_table("sales_funnel_summary_fsep66")], ["month"])
        )),
        # In the PBIT, euwwlz.month is displayed as action_month.
        "action_month": option_values([get_table("sales_flow_summary_euwwlz")], ["month"]),
        "application_created_month": option_values(base_tables, ["application_created_month"]),
        "uw_end_month": option_values(base_tables, ["uw_end_month"]),
        "current_lead_state": option_values(base_tables, ["current_lead_state_n"]),
        "lead_recency_flag": option_values(base_tables, ["lead_recency_flag"]),
        "current_application_state": option_values(base_tables, ["current_application_state"]),
        "app_state_age": option_values(base_tables, ["app_state_age"]),
        "uw_rejected_tag": option_values(base_tables, ["uw_rejected_tag"]),
        "ts_generated": option_values(base_tables, ["TERM_SHEET_GENERATED_TAG"]),
        "bre_rejection_tag": option_values(base_tables, ["BRE_rejection_tag"]),
        "uw_decision_poc": option_values(base_tables, ["uw_decision_poc"]),
        "sales_manager": option_values(base_tables, ["sales_manager"]),
        "sales_team": option_values(base_tables, ["sales_team"]),
    }


# Computed once at import — reused on every layout() call with zero SQL cost.
_FILTER_OPTS: Dict[str, List[str]] = _build_filter_options()
_REFRESH_TEXT: str = latest_refresh_text()


def refresh_data():
    """Atomically replace all Operational Metrics tables and slicer options."""
    global _query_cache, _REFRESH_TEXT
    with _refresh_lock:
        previous_cache = _query_cache
        candidate = QueryCache(CACHE_TTL_SEC)
        try:
            for table_name in _ALL_TABLES:
                frame = run_query(
                    f"SELECT * FROM {SCHEMA}.{table_name}",
                    context=f"operations:{table_name}",
                    raise_on_error=True,
                )
                candidate.put(table_name, frame)
            _query_cache = candidate
            refreshed_options = _build_filter_options()
            refreshed_text = latest_refresh_text()
        except Exception:
            _query_cache = previous_cache
            raise

        # Existing slicer definitions retain references to these lists, so
        # update each list in place instead of replacing the dictionary.
        for key in set(_FILTER_OPTS) | set(refreshed_options):
            _FILTER_OPTS.setdefault(key, [])[:]= refreshed_options.get(key, [])
        _REFRESH_TEXT = refreshed_text
        return True


# ---------------------------------------------------------------------------
# Per-tab slicer definitions (matching PBI page slicers exactly)
# ---------------------------------------------------------------------------
_SLICER_ROW = {"display": "flex", "flexWrap": "wrap", "gap": "10px", "marginBottom": "14px"}

_TAB_SLICERS = {
    "onboarding": [
        ("Team", "ops-s-onb-team", _FILTER_OPTS.get("team", [])),
        ("reporting_manager", "ops-s-onb-rm", _FILTER_OPTS.get("reporting_manager", [])),
        ("officer", "ops-s-onb-officer", _FILTER_OPTS.get("officer", [])),
        ("application_purpose", "ops-s-onb-purpose", _FILTER_OPTS.get("application_purpose", [])),
        ("lead_BD", "ops-s-onb-leadbd", _FILTER_OPTS.get("lead_bd", [])),
        ("employee_status", "ops-s-onb-empst", option_values([get_table("bridge_table_slicers_oatmop")], ["employee_status"])),
        ("visited_by (anchor_poc)", "ops-s-onb-visited", _FILTER_OPTS.get("officer", [])),
    ],
    "flow": [
        ("Team", "ops-s-flow-team", _FILTER_OPTS.get("team", [])),
        ("reporting_manager", "ops-s-flow-rm", _FILTER_OPTS.get("reporting_manager", [])),
        ("officer", "ops-s-flow-officer", _FILTER_OPTS.get("officer", [])),
        ("anchor_name", "ops-s-flow-anchor", _FILTER_OPTS.get("anchor_name", [])),
        ("lead_upload_month", "ops-s-flow-leaduploadmonth", _FILTER_OPTS.get("lead_upload_month", [])),
        ("action_month", "ops-s-flow-actionmonth", _FILTER_OPTS.get("action_month", [])),
        ("sprint", "ops-s-flow-sprint", _FILTER_OPTS.get("sprint", [])),
        ("lead_sourced_by", "ops-s-flow-leadsourcedby", _FILTER_OPTS.get("lead_sourced_by", [])),
        ("lead_source_tag", "ops-s-flow-source", _FILTER_OPTS.get("lead_source_tag", [])),
        ("lead_bd", "ops-s-flow-leadbd", _FILTER_OPTS.get("lead_bd", [])),
    ],
    "anchor": [
        ("Team", "ops-s-anc-team", _FILTER_OPTS.get("team", [])),
        ("reporting_manager", "ops-s-anc-rm", _FILTER_OPTS.get("reporting_manager", [])),
        ("officer", "ops-s-anc-officer", _FILTER_OPTS.get("officer", [])),
        ("anchor_name", "ops-s-anc-anchor", _FILTER_OPTS.get("anchor_name", [])),
        ("lead_upload_month", "ops-s-anc-leaduploadmonth", _FILTER_OPTS.get("lead_upload_month", [])),
        ("action_month", "ops-s-anc-actionmonth", _FILTER_OPTS.get("action_month", [])),
        ("sprint", "ops-s-anc-sprint", _FILTER_OPTS.get("sprint", [])),
        ("lead_sourced_by", "ops-s-anc-leadsourcedby", _FILTER_OPTS.get("lead_sourced_by", [])),
        ("lead_source_tag", "ops-s-anc-source", _FILTER_OPTS.get("lead_source_tag", [])),
        ("lead_bd", "ops-s-anc-leadbd", _FILTER_OPTS.get("lead_bd", [])),
    ],
    "leadbd": [
        ("Team", "ops-s-lb-team", _FILTER_OPTS.get("team", [])),
        ("reporting_manager", "ops-s-lb-rm", _FILTER_OPTS.get("reporting_manager", [])),
        ("officer", "ops-s-lb-officer", _FILTER_OPTS.get("officer", [])),
        ("anchor_name", "ops-s-lb-anchor", _FILTER_OPTS.get("anchor_name", [])),
        ("lead_upload_month", "ops-s-lb-leaduploadmonth", _FILTER_OPTS.get("lead_upload_month", [])),
        ("action_month", "ops-s-lb-actionmonth", _FILTER_OPTS.get("action_month", [])),
        ("sprint", "ops-s-lb-sprint", _FILTER_OPTS.get("sprint", [])),
        ("lead_sourced_by", "ops-s-lb-leadsourcedby", _FILTER_OPTS.get("lead_sourced_by", [])),
        ("lead_source_tag", "ops-s-lb-source", _FILTER_OPTS.get("lead_source_tag", [])),
        ("lead_bd", "ops-s-lb-leadbd", _FILTER_OPTS.get("lead_bd", [])),
    ],
    "rejection": [
        ("application_created_month", "ops-s-rej-applicationmonth", _FILTER_OPTS.get("application_created_month", [])),
        ("uw_rejected_tag", "ops-s-rej-uwrejected", _FILTER_OPTS.get("uw_rejected_tag", [])),
        ("ts_generated", "ops-s-rej-tsgenerated", _FILTER_OPTS.get("ts_generated", [])),
        ("bre_rejection_tag", "ops-s-rej-brerejection", _FILTER_OPTS.get("bre_rejection_tag", [])),
        ("uw_decision_poc", "ops-s-rej-uwdecisionpoc", _FILTER_OPTS.get("uw_decision_poc", [])),
        ("anchor_name", "ops-s-rej-anchor", _FILTER_OPTS.get("anchor_name", [])),
        ("sales_manager", "ops-s-rej-salesmanager", _FILTER_OPTS.get("sales_manager", [])),
        ("sales_team", "ops-s-rej-salesteam", _FILTER_OPTS.get("sales_team", [])),
    ],
}

_STATE_LEAD_SLICERS = [
    ("Team", "ops-s-st-lead-team", _FILTER_OPTS.get("team", [])),
    ("reporting_manager", "ops-s-st-lead-rm", _FILTER_OPTS.get("reporting_manager", [])),
    ("officer", "ops-s-st-lead-officer", _FILTER_OPTS.get("officer", [])),
    ("Anchor", "ops-s-st-lead-anchor", _FILTER_OPTS.get("anchor_name", [])),
    ("current_lead_state", "ops-s-st-lead-currentleadstate", _FILTER_OPTS.get("current_lead_state", [])),
    ("lead_upload_month", "ops-s-st-lead-leaduploadmonth", _FILTER_OPTS.get("lead_upload_month", [])),
    ("lead_bd", "ops-s-st-lead-leadbd", _FILTER_OPTS.get("lead_bd", [])),
    ("lead_recency_flag", "ops-s-st-lead-leadrecency", _FILTER_OPTS.get("lead_recency_flag", [])),
    ("lead_source_tag", "ops-s-st-lead-source", _FILTER_OPTS.get("lead_source_tag", [])),
]

_STATE_APP_SLICERS = [
    ("Team", "ops-s-st-app-team", _FILTER_OPTS.get("team", [])),
    ("reporting_manager", "ops-s-st-app-rm", _FILTER_OPTS.get("reporting_manager", [])),
    ("officer", "ops-s-st-app-officer", _FILTER_OPTS.get("officer", [])),
    ("current_application_state", "ops-s-st-app-currentappstate", _FILTER_OPTS.get("current_application_state", [])),
    ("anchor_name", "ops-s-st-app-anchor", _FILTER_OPTS.get("anchor_name", [])),
    ("lead_upload_month", "ops-s-st-app-leaduploadmonth", _FILTER_OPTS.get("lead_upload_month", [])),
    ("application_created_month", "ops-s-st-app-applicationmonth", _FILTER_OPTS.get("application_created_month", [])),
    ("app_state_age", "ops-s-st-app-appstateage", _FILTER_OPTS.get("app_state_age", [])),
    ("lead_BD", "ops-s-st-app-leadbd", _FILTER_OPTS.get("lead_bd", [])),
    ("application_purpose", "ops-s-st-app-purpose", _FILTER_OPTS.get("application_purpose", [])),
]

# Map tab slicer IDs back to filter keys for apply_filters
_SLICER_KEY_MAP = {
    "team": "team",
    "rm": "reporting_manager",
    "officer": "officer",
    "purpose": "application_purpose",
    "leadbd": "lead_bd",
    "anchor": "anchor_name",
    "source": "lead_source_tag",
    "leadsourcedby": "lead_sourced_by",
    "sprint": "sprint",
    "month": "month",
    "leaduploadmonth": "lead_upload_month",
    "actionmonth": "action_month",
    "applicationmonth": "application_created_month",
    "uwendmonth": "uw_end_month",
    "salesteam": "sales_team",
    "empst": "employee_status",
    "visited": "visited_by",
    "currentleadstate": "current_lead_state",
    "leadrecency": "lead_recency_flag",
    "currentappstate": "current_application_state",
    "appstateage": "app_state_age",
    "uwrejected": "uw_rejected_tag",
    "tsgenerated": "ts_generated",
    "brerejection": "bre_rejection_tag",
    "uwdecisionpoc": "uw_decision_poc",
    "salesmanager": "sales_manager",
}


def _collect_slicer_ids() -> List[str]:
    """Flat list of ALL slicer component IDs across all tabs."""
    ids = []
    for slicers in _TAB_SLICERS.values():
        for _, sid, _ in slicers:
            ids.append(sid)
    return ids


_ALL_SLICER_IDS = _collect_slicer_ids()
_STATE_LEAD_IDS = [slicer_id for _, slicer_id, _ in _STATE_LEAD_SLICERS]
_STATE_APP_IDS = [slicer_id for _, slicer_id, _ in _STATE_APP_SLICERS]

for _tab_key, _slicers in _TAB_SLICERS.items():
    register_filter_reset(
        f"ops-clear-{_tab_key}",
        [slicer_id for _, slicer_id, _ in _slicers],
    )
register_filter_reset("ops-clear-state-lead", _STATE_LEAD_IDS)
register_filter_reset("ops-clear-state-app", _STATE_APP_IDS)


def _read_filters_from_definitions(
    slicers,
    all_values: Dict[str, list],
) -> Dict[str, List[str]]:
    filters = {}
    for _, sid, _ in slicers:
        vals = all_values.get(sid) or []
        if not vals:
            continue
        key = sid.rsplit("-", 1)[-1]
        logical_key = _SLICER_KEY_MAP.get(key, key)
        filters[logical_key] = vals
    return filters


def _read_filters_from_inputs(tab: str, all_values: Dict[str, list]) -> Dict[str, List[str]]:
    """Given the active tab and a dict of slicer_id -> selected values, build the filters dict."""
    return _read_filters_from_definitions(_TAB_SLICERS.get(tab, []), all_values)


def _filters_for_tab(tab: str, slicer_values) -> Dict[str, List[str]]:
    return _read_filters_from_inputs(tab, dict(zip(_ALL_SLICER_IDS, slicer_values)))


def _state_filter_panel(title: str, slicers, clear_button_id: str):
    return html.Div([
        html.Div(title, style={"fontSize": "13px", "fontWeight": "700", "marginBottom": "10px"}),
        html.Div(
            [make_dropdown(label, sid, opts) for label, sid, opts in slicers]
            + [clear_filters_button(clear_button_id)],
            style=_SLICER_ROW,
        ),
    ], style={
        "background": CARD_BG, "border": f"1px solid {BORDER}",
        "borderRadius": "8px", "padding": "14px", "marginBottom": "16px",
    })


def _matrix_selection_banner(label_id: str, clear_id: str):
    return html.Div([
        html.Span("Raw-data filter: ", style={"fontWeight": "700"}),
        html.Span("No matrix cell selected", id=label_id),
        html.Button(
            "Clear selected cell", id=clear_id, n_clicks=0,
            className="ui-clear-filters", style={"marginLeft": "12px"},
        ),
    ], style={
        "display": "flex", "alignItems": "center", "flexWrap": "wrap",
        "gap": "6px", "fontSize": "12px", "marginBottom": "10px",
    })


def _state_view_layout():
    """Static layout keeps both section-specific slicer sets callback-addressable."""
    return html.Div([
        dcc.Store(id="ops-state-lead-crossfilter"),
        dcc.Store(id="ops-state-app-crossfilter"),
        html.Div([
            html.H3("Lead view", style={"fontSize": "18px", "fontWeight": "700", "marginBottom": "12px"}),
            _state_filter_panel("Lead filters", _STATE_LEAD_SLICERS, "ops-clear-state-lead"),
            section_title("Lead stock by anchor and current lead state"),
            html.Div(id="ops-state-lead-state-output"),
            html.Div(style={"height": "18px"}),
            section_title("Lead stock by anchor and worked age bucket"),
            html.Div(id="ops-state-lead-age-output"),
            html.Div(style={"height": "18px"}),
            section_title("Lead detail"),
            _matrix_selection_banner("ops-state-lead-selection-label", "ops-clear-state-lead-cell"),
            full_export_controls("ops-export-leads-all", "ops-download-leads-all"),
            html.Div(id="ops-state-lead-detail-output"),
        ], className="ops-state-section ops-state-section--lead"),
        html.Div(style={"height": "34px", "borderTop": f"3px solid {RED}", "marginTop": "28px"}),
        html.Div([
            html.H3("Application view", style={"fontSize": "18px", "fontWeight": "700", "marginBottom": "12px"}),
            _state_filter_panel("Application filters", _STATE_APP_SLICERS, "ops-clear-state-app"),
            section_title("Application stock by anchor and current state"),
            html.Div(id="ops-state-app-state-output"),
            html.Div(style={"height": "18px"}),
            section_title("Application stock by anchor and age bucket"),
            html.Div(id="ops-state-app-age-output"),
            html.Div(style={"height": "18px"}),
            section_title("Application detail"),
            _matrix_selection_banner("ops-state-app-selection-label", "ops-clear-state-app-cell"),
            full_export_controls("ops-export-apps-all", "ops-download-apps-all"),
            html.Div(id="ops-state-app-detail-output"),
        ], className="ops-state-section ops-state-section--application"),
    ], id="ops-state-view", style={"display": "none"})


def layout():
    # Build per-tab slicer groups (all in layout, visibility toggled by callback)
    slicer_groups = []
    for tab_key, slicers in _TAB_SLICERS.items():
        slicer_groups.append(
            html.Div(
                [make_dropdown(label, sid, opts) for label, sid, opts in slicers]
                + [clear_filters_button(f"ops-clear-{tab_key}")],
                id=f"ops-slicers-{tab_key}",
                style={**_SLICER_ROW, "display": "flex" if tab_key == "onboarding" else "none"},
            )
        )

    return html.Div([
        header_ui("uC : Onboarding", title_id="ops-page-title",
                  updated_text=_REFRESH_TEXT),
        tab_bar(TAB_NAMES, id_prefix="ops-nav-", active="onboarding"),
        dcc.Store(id="ops-active-tab", data="onboarding"),
        # Per-tab slicers (below tab bar, only active tab's group is visible)
        html.Div(slicer_groups, style={"marginBottom": "10px"}),
        # Content
        dcc.Loading(
            html.Div([
                html.Div(id="ops-standard-view", children=html.Div(id="ops-subpage-content")),
                _state_view_layout(),
            ]),
            type="dot", color=RED,
            style={"minHeight": "300px"},
        ),
    ], style={"padding": "24px 28px", "background": BG, "minHeight": "100vh"})


_PAGE_TITLES = {
    "onboarding": "uC : Onboarding",
    "flow": "Funnel / Flow summary",
    "anchor": "Anchor performance",
    "state": "Anchor \u2013 Current State View",
    "leadbd": "Lead_BD performance",
    "rejection": "Rejection cause",
}


@callback(
    Output("ops-active-tab", "data"),
    [Input(f"ops-nav-{v}", "n_clicks") for v, _ in TAB_NAMES]
    + [Input("ops-nav-mobile", "value")],
    prevent_initial_call=True,
)
def on_tab_click(*values):
    from dash import ctx, no_update
    tid = ctx.triggered_id
    if tid is None:
        return no_update
    if tid == "ops-nav-mobile":
        selected = values[-1] or no_update
    else:
        selected = tid.replace("ops-nav-", "")
    if selected is not no_update:
        track_tab_click("operations", selected)
    return selected


@callback(
    [Output(f"ops-nav-{v}", "className") for v, _ in TAB_NAMES]
    + [Output(f"ops-slicers-{v}", "style") for v in _TAB_SLICERS]
    + [Output("ops-standard-view", "style"), Output("ops-state-view", "style")]
    + [Output("ops-page-title", "children")],
    Input("ops-active-tab", "data"),
)
def highlight_tab_and_show_slicers(active):
    btn_styles = ["ui-tab active" if v == active else "ui-tab" for v, _ in TAB_NAMES]
    slicer_styles = [
        {**_SLICER_ROW, "display": "flex"} if v == active else {"display": "none"}
        for v in _TAB_SLICERS
    ]
    standard_style = {"display": "none"} if active == "state" else {"display": "block"}
    state_style = {"display": "block"} if active == "state" else {"display": "none"}
    title = _PAGE_TITLES.get(active, "Operational Metrics")
    return btn_styles + slicer_styles + [standard_style, state_style, title]


@callback(
    Output("ops-subpage-content", "children"),
    Input("ops-active-tab", "data"),
    [Input(sid, "value") for sid in _ALL_SLICER_IDS],
)
def render_content(tab, *slicer_values):
    alias_filters = _filters_for_tab(tab, slicer_values)
    renderers = {
        "onboarding": render_onboarding,
        "flow": render_flow_summary,
        "anchor": render_anchor_performance,
        "leadbd": render_lead_bd_performance,
        "rejection": render_rejection_cause,
    }
    if tab == "state":
        return html.Div()
    if tab in renderers:
        with visual_scope("operations", tab):
            return renderers[tab](alias_filters)
    return empty_state("Select a sub-page.")


@callback(
    [
        Output("ops-state-lead-state-output", "children"),
        Output("ops-state-lead-age-output", "children"),
        Output("ops-state-lead-detail-output", "children"),
        Output("ops-state-app-state-output", "children"),
        Output("ops-state-app-age-output", "children"),
        Output("ops-state-app-detail-output", "children"),
        Output("ops-state-lead-selection-label", "children"),
        Output("ops-state-app-selection-label", "children"),
    ],
    [Input("ops-active-tab", "data")]
    + [Input(component_id, "value") for component_id in _STATE_LEAD_IDS]
    + [Input(component_id, "value") for component_id in _STATE_APP_IDS]
    + [Input("ops-state-lead-crossfilter", "data"), Input("ops-state-app-crossfilter", "data")],
)
def render_current_state_sections(active_tab, *values):
    if active_tab != "state":
        return [no_update] * 8
    lead_count = len(_STATE_LEAD_IDS)
    app_count = len(_STATE_APP_IDS)
    lead_values = values[:lead_count]
    app_values = values[lead_count:lead_count + app_count]
    lead_selection, app_selection = values[-2:]
    lead_filters = _read_filters_from_definitions(
        _STATE_LEAD_SLICERS, dict(zip(_STATE_LEAD_IDS, lead_values)),
    )
    app_filters = _read_filters_from_definitions(
        _STATE_APP_SLICERS, dict(zip(_STATE_APP_IDS, app_values)),
    )
    with visual_scope("operations", "state"):
        visuals = render_current_state_views(
            lead_filters, app_filters, lead_selection, app_selection,
        )
    return list(visuals) + [
        matrix_selection_label(lead_selection),
        matrix_selection_label(app_selection),
    ]


@callback(
    Output("ops-state-lead-crossfilter", "data"),
    Input({"type": "ui-summary-table", "index": "ops-state-lead-state-matrix"}, "active_cell"),
    Input({"type": "ui-summary-table", "index": "ops-state-lead-age-matrix"}, "active_cell"),
    Input("ops-clear-state-lead-cell", "n_clicks"),
    Input("ops-clear-state-lead", "n_clicks"),
    State({"type": "ui-summary-table", "index": "ops-state-lead-state-matrix"}, "derived_virtual_data"),
    State({"type": "ui-summary-table", "index": "ops-state-lead-age-matrix"}, "derived_virtual_data"),
    prevent_initial_call=True,
)
def select_lead_matrix_cell(state_cell, age_cell, _clear_cell, _clear_all, state_rows, age_rows):
    triggered = ctx.triggered_id
    if isinstance(triggered, str) and triggered in {"ops-clear-state-lead-cell", "ops-clear-state-lead"}:
        return None
    if not isinstance(triggered, dict):
        return no_update
    if triggered.get("index") == "ops-state-lead-state-matrix":
        selection = matrix_cell_selection(
            state_cell, state_rows,
            row_field="Anchor", column_field="current_lead_state_n",
        )
    else:
        selection = matrix_cell_selection(
            age_cell, age_rows,
            row_field="Anchor", column_field="lead_worked_age_bucket",
        )
    return selection if selection else no_update


@callback(
    Output("ops-state-app-crossfilter", "data"),
    Input({"type": "ui-summary-table", "index": "ops-state-app-state-matrix"}, "active_cell"),
    Input({"type": "ui-summary-table", "index": "ops-state-app-age-matrix"}, "active_cell"),
    Input("ops-clear-state-app-cell", "n_clicks"),
    Input("ops-clear-state-app", "n_clicks"),
    State({"type": "ui-summary-table", "index": "ops-state-app-state-matrix"}, "derived_virtual_data"),
    State({"type": "ui-summary-table", "index": "ops-state-app-age-matrix"}, "derived_virtual_data"),
    prevent_initial_call=True,
)
def select_app_matrix_cell(state_cell, age_cell, _clear_cell, _clear_all, state_rows, age_rows):
    triggered = ctx.triggered_id
    if isinstance(triggered, str) and triggered in {"ops-clear-state-app-cell", "ops-clear-state-app"}:
        return None
    if not isinstance(triggered, dict):
        return no_update
    if triggered.get("index") == "ops-state-app-state-matrix":
        selection = matrix_cell_selection(
            state_cell, state_rows,
            row_field="anchor_name", column_field="current_application_state",
        )
    else:
        selection = matrix_cell_selection(
            age_cell, age_rows,
            row_field="anchor_name", column_field="app_state_age_bucket",
        )
    return selection if selection else no_update


@callback(
    Output("ops-download-leads-all", "data"),
    Input("ops-export-leads-all", "n_clicks"),
    [State(component_id, "value") for component_id in _STATE_LEAD_IDS]
    + [State("ops-state-lead-crossfilter", "data")],
    prevent_initial_call=True,
)
def export_all_operational_leads(_n_clicks, *values):
    slicer_values, selection = values[:-1], values[-1]
    filters = _read_filters_from_definitions(
        _STATE_LEAD_SLICERS, dict(zip(_STATE_LEAD_IDS, slicer_values)),
    )
    frame = filter_table(get_table("lead_stock_uc_ipyaib"), filters)
    frame = apply_matrix_selection(frame, selection)
    columns = [column for column in LEAD_DETAIL_COLUMNS if column in frame.columns]
    if frame.empty or not columns:
        return no_update
    return dcc.send_data_frame(
        frame[columns].to_csv,
        "operational_leads_filtered.csv",
        index=False,
    )


@callback(
    Output("ops-download-apps-all", "data"),
    Input("ops-export-apps-all", "n_clicks"),
    [State(component_id, "value") for component_id in _STATE_APP_IDS]
    + [State("ops-state-app-crossfilter", "data")],
    prevent_initial_call=True,
)
def export_all_operational_apps(_n_clicks, *values):
    slicer_values, selection = values[:-1], values[-1]
    filters = _read_filters_from_definitions(
        _STATE_APP_SLICERS, dict(zip(_STATE_APP_IDS, slicer_values)),
    )
    frame = filter_table(get_table("app_stock_uc_fvx6ys"), filters)
    frame = apply_matrix_selection(frame, selection)
    columns = [column for column in APP_DETAIL_COLUMNS if column in frame.columns]
    if frame.empty or not columns:
        return no_update
    return dcc.send_data_frame(
        frame[columns].to_csv,
        "operational_applications_filtered.csv",
        index=False,
    )


@callback(
    Output("ops-download-rejections-all", "data"),
    Input("ops-export-rejections-all", "n_clicks"),
    [State(component_id, "value") for component_id in _ALL_SLICER_IDS],
    prevent_initial_call=True,
)
def export_all_operational_rejections(_n_clicks, *slicer_values):
    filters = _filters_for_tab("rejection", slicer_values)
    frame = filter_table(get_table("rejection_tracking_kh32o2"), filters)
    if frame.empty:
        return no_update
    return dcc.send_data_frame(
        frame.to_csv,
        "operational_rejections_filtered.csv",
        index=False,
    )
