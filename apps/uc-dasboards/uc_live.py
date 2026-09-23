import dash
from dash import html, dcc, callback, Output, Input
import dash_bootstrap_components as dbc
import pandas as pd
import os
import time
import sys
from ui import (
    header_ui, kpi_card, multi_line_chart, visual_card, error_state,
    with_visual_scope,
)
from shared import format_timestamp, run_queries

# --- Data fetching ---
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "e6b3b3d8399e5edb")

_cache = {}
_cache_ttl = 1800  # 30 minutes


def fetch_data():
    now = time.time()
    if "data" in _cache and (now - _cache["ts"]) < _cache_ttl:
        return _cache["data"]

    try:
        frames = run_queries(
            {
                "aum": "SELECT product_type, aum, updated_at, drawdown_today, settlement_today FROM hive_metastore.probes.live_dashboard_aum_gjizpf",
                "hcpl": "SELECT product_type, updated_at, aum, drawdown_today, settlement_today FROM hive_metastore.probes.live_dashboard_hcpl_lcwxtn",
                "activations": "SELECT updated_at, line_today, line_sprint, line_mtd FROM hive_metastore.probes.live_dashboard_new_actvations_gxbrta",
                "aum_graph": "SELECT day_month, M_AUM, M_1_AUM, M_2_AUM, M_3_AUM, M_12_AUM, M_24_AUM FROM hive_metastore.probes.aum_graph_gfngvh",
                "disbursal": "SELECT DayOfMonth, M, M_1, M_2, M_3, updated_at FROM hive_metastore.probes.live_dashboard_disb_trendline_7udbqb",
            },
            warehouse_id=WAREHOUSE_ID,
            context="live-status",
            raise_on_error=True,
        )
    except Exception as exc:
        print(f"ERROR: Failed to load live-status data: {exc}", file=sys.stderr)
        return None, None, None, None, None

    data = (
        frames["aum"],
        frames["hcpl"],
        frames["activations"],
        frames["aum_graph"],
        frames["disbursal"],
    )
    _cache["data"] = data
    _cache["ts"] = now
    return data






@with_visual_scope("live", "main")
def build_layout():
    df_aum, df_hcpl, df_activations, df_aum_graph, df_disb = fetch_data()

    if df_aum is None:
        return error_state("Failed to connect to data source. Check app logs for details.")

    if df_aum.empty and df_hcpl.empty and df_activations.empty:
        return error_state("All queries returned empty results. The app service principal may lack SELECT access.")

    # --- Compute KPIs ---
    try:
        df_aum["aum"] = pd.to_numeric(df_aum["aum"], errors="coerce")
        df_aum["drawdown_today"] = pd.to_numeric(df_aum["drawdown_today"], errors="coerce")
        df_aum["settlement_today"] = pd.to_numeric(df_aum["settlement_today"], errors="coerce")
        current_aum = df_aum["aum"].sum()
        disbursals_today = df_aum["drawdown_today"].sum()
        repayments_today = df_aum["settlement_today"].sum()
    except:
        current_aum = disbursals_today = repayments_today = 0

    try:
        df_hcpl["aum"] = pd.to_numeric(df_hcpl["aum"], errors="coerce")
        df_hcpl["drawdown_today"] = pd.to_numeric(df_hcpl["drawdown_today"], errors="coerce")
        df_hcpl["settlement_today"] = pd.to_numeric(df_hcpl["settlement_today"], errors="coerce")
        hcpl_aum = df_hcpl["aum"].sum()
        hcpl_disb = df_hcpl["drawdown_today"].sum()
        hcpl_repay = df_hcpl["settlement_today"].sum()
    except:
        hcpl_aum = hcpl_disb = hcpl_repay = 0

    try:
        new_today = int(float(df_activations["line_today"].iloc[0])) if not df_activations.empty else 0
        new_sprint = int(float(df_activations["line_sprint"].iloc[0])) if not df_activations.empty else 0
        new_mtd = int(float(df_activations["line_mtd"].iloc[0])) if not df_activations.empty else 0
    except:
        new_today = new_sprint = new_mtd = 0

    # --- Timestamp ---
    raw_ts = df_aum["updated_at"].iloc[0] if not df_aum.empty else "N/A"
    display_ts = format_timestamp(raw_ts)

    # --- Header ---
    header = header_ui("uC : Live Status", updated_text=display_ts)

    # --- KPI Rows ---
    kpi_row1 = dbc.Row(
        [
            # Visual 1.1.1 | widget | gjizpf | Current AUM (Cr)
            dbc.Col(kpi_card("Current AUM (Cr)", f"{current_aum:.2f}", track_visual=True), md=4),
            # Visual 1.1.2 | widget | gjizpf | Disbursals Today (Cr)
            dbc.Col(kpi_card("Disbursals Today (Cr)", f"{disbursals_today:.2f}", track_visual=True), md=4),
            # Visual 1.1.3 | widget | gjizpf | Repayments Today (Cr)
            dbc.Col(kpi_card("Repayments Today (Cr)", f"{repayments_today:.2f}", track_visual=True), md=4),
        ],
        className="g-2 mb-2"
    )

    kpi_row2 = dbc.Row(
        [
            # Visual 1.1.4 | widget | lcwxtn | Current AUM (Cr) - HCPL
            dbc.Col(kpi_card("Current AUM (Cr) \u2014 HCPL", f"{hcpl_aum:.2f}", track_visual=True), md=4),
            # Visual 1.1.5 | widget | lcwxtn | Disbursals Today (Cr) - HCPL
            dbc.Col(kpi_card("Disbursals Today (Cr) \u2014 HCPL", f"{hcpl_disb:.2f}", track_visual=True), md=4),
            # Visual 1.1.6 | widget | lcwxtn | Repayments Today (Cr) - HCPL
            dbc.Col(kpi_card("Repayments Today (Cr) \u2014 HCPL", f"{hcpl_repay:.2f}", track_visual=True), md=4),
        ],
        className="g-2 mb-2"
    )

    kpi_row3 = dbc.Row(
        [
            # Visual 1.1.7 | widget | gxbrta | New Users - Today
            dbc.Col(kpi_card("New Users \u2014 Today", str(new_today), track_visual=True), md=4),
            # Visual 1.1.8 | widget | gxbrta | New Users - Sprint
            dbc.Col(kpi_card("New Users \u2014 Sprint", str(new_sprint), track_visual=True), md=4),
            # Visual 1.1.9 | widget | gxbrta | New Users - MTD
            dbc.Col(kpi_card("New Users \u2014 MTD", str(new_mtd), track_visual=True), md=4),
        ],
        className="g-2"
    )

    # --- Charts (shared chart renderer; only data/series are page-specific) ---
    if not df_aum_graph.empty:
        df_aum_graph["day_month"] = pd.to_numeric(df_aum_graph["day_month"], errors="coerce")
        for c in ["M_AUM", "M_1_AUM", "M_2_AUM", "M_3_AUM", "M_12_AUM", "M_24_AUM"]:
            df_aum_graph[c] = pd.to_numeric(df_aum_graph[c], errors="coerce")
        df_aum_graph = df_aum_graph.sort_values("day_month")
    if not df_disb.empty:
        df_disb["DayOfMonth"] = pd.to_numeric(df_disb["DayOfMonth"], errors="coerce")
        for c in ["M", "M_1", "M_2", "M_3"]:
            df_disb[c] = pd.to_numeric(df_disb[c], errors="coerce")
        df_disb = df_disb.sort_values("DayOfMonth")

    # Visual 1.1.10 | chart | gfngvh | AUM (Cr)
    aum_chart = multi_line_chart(
        df_aum_graph, "day_month",
        ["M_24_AUM", "M_12_AUM", "M_3_AUM", "M_2_AUM", "M_1_AUM", "M_AUM"],
        "AUM (Cr)", labels=["M-24", "M-12", "M-3", "M-2", "M-1", "Current"],
        colors=["#94A3B8", "#64748B", "#06B6D4", "#F59E0B", "#8B5CF6", "#DC3545"], smooth=True,
    )
    # Visual 1.1.11 | chart | 7udbqb | Disbursals (Cr)
    disb_chart = multi_line_chart(
        df_disb, "DayOfMonth", ["M_3", "M_2", "M_1", "M"], "Disbursals (Cr)",
        labels=["M-3", "M-2", "M-1", "Current"],
        colors=["#06B6D4", "#F59E0B", "#8B5CF6", "#DC3545"], smooth=True,
    )

    charts_row = dbc.Row(
        [
            dbc.Col(visual_card(aum_chart), md=6),
            dbc.Col(visual_card(disb_chart), md=6),
        ],
        className="g-2 mt-2"
    )

    # --- Full Layout ---
    return dbc.Container(
        [
            header,
            kpi_row1,
            kpi_row2,
            kpi_row3,
            charts_row,
        ],
        className="live-status-page",
        fluid=True,
        style={"padding": "1.2rem 2rem 1rem 2rem", "maxWidth": "100%", "background": "#f0f0f3", "minHeight": "100vh",
               "fontFamily": "'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif"}
    )



def layout():
    """Return the full UC Live Status layout including auto-refresh."""
    return html.Div([
        dcc.Interval(id="ul-refresh-interval", interval=3600 * 1000, n_intervals=0),
        html.Div(id="ul-main-content", children=build_layout())
    ])


@callback(
    Output("ul-main-content", "children"),
    [Input("ul-refresh-interval", "n_intervals")]
)
def refresh_layout(n):
    if n and n > 0:
        _cache.clear()
    return build_layout()
