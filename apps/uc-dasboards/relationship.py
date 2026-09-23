"""Relationship Tracker — Pivot-table-only dashboard replicating the Power BI report."""
import os, sys
import pandas as pd
from dash import Dash, html, dcc, callback, Input, Output, State, ctx, no_update
from datetime import datetime
from functools import partial
from ui import (
    NAVIGATION, filter_ui, header_ui, tab_bar, download_button,
    table_ui, visual_card, error_state, theme_value, identified_visual,
    clear_filters_button, register_filter_reset, visual_scope, with_visual_scope,
)
from shared import (
    filter_frame as filt,
    format_timestamp,
    make_pivot as make_pivot_frame,
    run_query as shared_run_query,
    track_tab_click,
    unique_values as uvals,
)

WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "e6b3b3d8399e5edb")
REFRESH_MS = int(os.getenv("REFRESH_INTERVAL_MS", "900000"))

run_query = partial(
    shared_run_query,
    warehouse_id=WAREHOUSE_ID,
    context="relationship",
    raise_on_error=True,
)


def load_data():
    d = {}
    d["ts"] = run_query("""
        SELECT check_date, agent_email, sales_manager_email, zonal_manager,
               anchor, lender, role, state, plt_anchor, PLT_Anchor_Plus_Term_Loan,
               SUM(aum) AS aum, MAX(refresh_time) AS refresh_time
        FROM hive_metastore.probes.rm_tracking_gpnbka
        GROUP BY check_date, agent_email, sales_manager_email, zonal_manager,
                 anchor, lender, role, state, plt_anchor, PLT_Anchor_Plus_Term_Loan
    """)
    d["raw"] = run_query("""
        SELECT * FROM hive_metastore.probes.rm_tracking_gpnbka
        WHERE check_date = (SELECT MAX(check_date) FROM hive_metastore.probes.rm_tracking_gpnbka)
    """)
    d["visits"] = run_query("SELECT * FROM hive_metastore.probes.visits_pbi_h2srrf")
    d["cv"] = run_query("""
        SELECT visited_by, name, role, manager_email, rsm, sprint,
               current_active, visit_reason, check_month,
               SUM(check_date_visits_for_reason) AS visits,
               MAX(refresh_time) AS refresh_time
        FROM hive_metastore.probes.cross_visits_hmnkwl
        GROUP BY visited_by, name, role, manager_email, rsm, sprint,
                 current_active, visit_reason, check_month
    """)
    d["cv_daily"] = run_query("""
        SELECT visited_by, check_date, SUM(check_date_visits_for_reason) AS visits
        FROM hive_metastore.probes.cross_visits_hmnkwl
        WHERE check_date >= (SELECT date_sub(MAX(check_date), 6) FROM hive_metastore.probes.cross_visits_hmnkwl)
        GROUP BY visited_by, check_date
    """)
    return d


DATA = {}
DATA_ERR = ""
DATA_AT = ""


def refresh():
    global DATA, DATA_ERR, DATA_AT
    try:
        DATA = load_data()
        DATA_ERR = ""
        DATA_AT = format_timestamp(datetime.now())
    except Exception as e:
        DATA_ERR = str(e)
        print(f"[ERROR] {e}", file=sys.stderr)


refresh()

# -- Design tokens --
ACCENT = theme_value("colors.primary", "#DC3545")
ACCENT_DARK = theme_value("colors.primary_dark", "#B81010")
RED = ACCENT
BG = theme_value("colors.background", "#F0F0F3")
CARD_BG = "#ffffff"
BORDER = theme_value("colors.border", "#E5E7EB")
TEXT = theme_value("colors.text", "#111111")
TEXT_LIGHT = theme_value("colors.muted", "#555555")
SPRINT_COLORS = {"S1": "#FFF1F3", "S2": "#FCE4E7", "S3": "#F8D4D9"}
SPRINT_HEADER_COLORS = {"S1": "#E35D6A", "S2": "#DC3545", "S3": "#B81010"}

def slicer(label, sid, opts):
    return filter_ui(label, sid, opts or [], multi=True, variant="accent")


def pivot_table(df, index_col, value_col="aum", title=""):
    """Create agent_email x check_date pivot with Total row."""
    if df.empty:
        return identified_visual(
            html.Div("No data", style={"padding": "20px", "textAlign": "center"}),
            "table",
        )
    pv = make_pivot_frame(
        df,
        rows=index_col,
        columns="check_date",
        values=value_col,
        aggfunc="sum",
    )
    if pv.empty:
        return identified_visual(
            html.Div("No data", style={"padding": "20px", "textAlign": "center"}),
            "table",
        )
    pv = pv.set_index(index_col)
    pv = pv.round(2)
    # Sort columns (dates)
    pv = pv.reindex(sorted(pv.columns), axis=1)
    # Add Total row (numeric, before formatting)
    pv.loc["Total"] = pv.sum(numeric_only=True)
    pv.loc["Total"] = pv.loc["Total"].round(2)
    pv = pv.reset_index()
    # Format: hide zeros, show 2 decimals
    for c in pv.columns[1:]:
        pv[c] = pv[c].apply(lambda x: "" if x == 0 else f"{x:.2f}")
    table = table_ui(pv, page_size=max(len(pv), 1), downloadable=False,
                     max_height=340, variant="primary")
    return visual_card(table, title=title) if title else table


def delta_table(df, index_col):
    """RSM delta table: Delta 6M, Delta 3M, Delta LM as percentages."""
    if df.empty:
        return identified_visual(html.Div("No data"), "table")
    df = df.copy()
    df["aum"] = pd.to_numeric(df["aum"], errors="coerce").fillna(0)
    df["check_date"] = pd.to_datetime(df["check_date"])
    dates = sorted(df["check_date"].unique())
    if len(dates) < 2:
        return identified_visual(html.Div("Insufficient data for deltas"), "table")
    latest = dates[-1]
    aum_latest = df[df["check_date"] == latest].groupby(index_col)["aum"].sum()
    def pct(months_back):
        target = latest - pd.DateOffset(months=months_back)
        past_dates = [d for d in dates if d <= target]
        if not past_dates:
            return pd.Series(dtype=float, index=aum_latest.index)
        closest = past_dates[-1]
        aum_past = df[df["check_date"] == closest].groupby(index_col)["aum"].sum()
        delta = ((aum_latest - aum_past) / aum_past.replace(0, float("nan")) * 100).round(1)
        return delta.reindex(aum_latest.index)
    result = pd.DataFrame({"Delta 6M": pct(6), "Delta 3M": pct(3), "Delta LM": pct(1)}, index=aum_latest.index)
    result = result.fillna("").reset_index()
    # Format as percentages
    for c in ["Delta 6M", "Delta 3M", "Delta LM"]:
        result[c] = result[c].apply(lambda x: f"{x}%" if x != "" else "")
    # Total row
    total_latest = aum_latest.sum()
    def total_pct(months_back):
        target = latest - pd.DateOffset(months=months_back)
        past_dates = [d for d in dates if d <= target]
        if not past_dates:
            return ""
        closest = past_dates[-1]
        past_total = df[df["check_date"] == closest].groupby(index_col)["aum"].sum().sum()
        if past_total == 0:
            return ""
        return f"{((total_latest - past_total) / past_total * 100):.1f}%"
    total_row = {index_col: "Total", "Delta 6M": total_pct(6), "Delta 3M": total_pct(3), "Delta LM": total_pct(1)}
    result = pd.concat([result, pd.DataFrame([total_row])], ignore_index=True)
    return table_ui(result, page_size=max(len(result), 1), downloadable=False,
                    max_height=340, variant="primary")


def error_banner(msg):
    return error_state(msg)


# -- App --
RT_TAB_CONFIG = sorted(NAVIGATION["subpages"]["relationship"], key=lambda item: item.get("order", 0))
RT_TABS = [item["id"] for item in RT_TAB_CONFIG]

_RELATIONSHIP_FILTER_GROUPS = {
    "sales": ["sa", "sl", "sr", "sp", "sm", "ss"],
    "rsm": ["ra", "rs", "rl", "rm", "rz"],
    "raw": ["xa", "xl", "xp", "xm", "xs", "xls", "xd", "xdd", "xk", "xci"],
    "visits": ["va", "vb", "vn", "vm", "vr", "van", "vs"],
}

for _tab_id, _filter_ids in _RELATIONSHIP_FILTER_GROUPS.items():
    register_filter_reset(f"rt-{_tab_id}-clear", _filter_ids)


def layout():
    return html.Div([
        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0),
        dcc.Store(id="ver", data=0),
        dcc.Download(id="dl-s"),
        dcc.Download(id="dl-r"),
        dcc.Download(id="dl-x"),
        dcc.Download(id="dl-v"),
        header_ui("Relationship Tracker", subtitle="", subtitle_id="page_title",
                  badge_id="badge", updated_text=DATA_AT),
        dcc.Store(id="rt-active-tab", data="sales"),
        tab_bar(RT_TAB_CONFIG, id_prefix="rt-tab-", active="sales"),
        html.Div(id="page", style={"padding": "20px 28px"}),
], style={"fontFamily": "Inter, -apple-system, sans-serif", "background": BG, "minHeight": "100vh",
          "color": TEXT})


@callback([Output("ver", "data"), Output("badge", "children")], Input("tick", "n_intervals"))
def on_tick(n):
    if n > 0:
        refresh()
    ts = DATA.get("ts")
    rt = ""
    if ts is not None and "refresh_time" in ts.columns:
        rt = ts["refresh_time"].dropna().max()
    badge = format_timestamp(rt, fallback=DATA_AT) if rt else DATA_AT
    return n, badge


@callback(
    Output("rt-active-tab", "data"),
    [Input(f"rt-tab-{t}", "n_clicks") for t in RT_TABS]
    + [Input("rt-tab-mobile", "value")],
    prevent_initial_call=True,
)
def rt_tab_click(*values):
    tid = ctx.triggered_id
    if tid is None:
        return no_update
    if tid == "rt-tab-mobile":
        selected = values[-1] or no_update
    else:
        selected = tid.replace("rt-tab-", "")
    if selected is not no_update:
        track_tab_click("relationship", selected)
    return selected


@callback(
    [Output(f"rt-tab-{t}", "className") for t in RT_TABS],
    Input("rt-active-tab", "data"),
)
def rt_highlight_tab(active):
    return [f"ui-tab{' active' if t == active else ''}" for t in RT_TABS]


@callback([Output("page", "children"), Output("page_title", "children")],
          [Input("rt-active-tab", "data"), Input("ver", "data")])
def render(tab, _):
    if DATA_ERR:
        return error_banner(DATA_ERR), "Error"
    pages = {
        "sales": (page_sales, "Month-On-Month AUM View - SALES POC"),
        "rsm": (page_rsm, "Month-On-Month AUM View - RSM"),
        "raw": (page_raw, "Raw Data"),
        "visits": (page_visits, "Daily Visits"),
    }
    if tab in pages:
        renderer, title = pages[tab]
        with visual_scope("relationship", tab):
            return renderer(), title
    return html.Div(), ""


# ============ SALES POC ============
def build_sales_tables(df):
    if df.empty:
        return html.Div("No data")
    df["plt_anchor"] = df["plt_anchor"].astype(str).str.lower()
    df["PLT_Anchor_Plus_Term_Loan"] = df["PLT_Anchor_Plus_Term_Loan"].astype(str).str.lower()
    plt_at = df[df["PLT_Anchor_Plus_Term_Loan"] == "true"]
    plt_a = df[df["plt_anchor"] == "true"]
    plt_na = df[(df["plt_anchor"] != "true") & (df["PLT_Anchor_Plus_Term_Loan"] != "true")]
    # Visual 3.1.1 | table | gpnbka | PLT Anchor + Term Loan
    # Visual 3.1.2 | table | gpnbka | PLT Anchor
    # Visual 3.1.3 | table | gpnbka | PLT Non Anchor
    return html.Div([
        pivot_table(plt_at, "agent_email", "aum", "PLT Anchor + Term Loan"),
        pivot_table(plt_a, "agent_email", "aum", "PLT Anchor"),
        pivot_table(plt_na, "agent_email", "aum", "PLT Non Anchor"),
    ])


def page_sales():
    df = DATA.get("ts")
    if df is None or df.empty:
        return html.Div("No data")
    return html.Div([
        html.Div([slicer("Anchor", "sa", uvals(df, "anchor")),
                  slicer("Lender", "sl", uvals(df, "lender")),
                  slicer("Role", "sr", uvals(df, "role")),
                  slicer("Sales POC", "sp", uvals(df, "agent_email")),
                  slicer("Regional Sales Manager", "sm", uvals(df, "sales_manager_email")),
                  slicer("State", "ss", uvals(df, "state")),
                  clear_filters_button("rt-sales-clear")],
                 style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginBottom": "20px"}),
        html.Div(id="sales_tables", children=build_sales_tables(df)),
        html.Div([download_button("ds", variant="primary")],
                 style={"textAlign": "right"}),
    ])


@callback(Output("sales_tables", "children"),
          [Input("sa", "value"), Input("sl", "value"), Input("sr", "value"),
           Input("sp", "value"), Input("sm", "value"), Input("ss", "value"), Input("ver", "data")])
@with_visual_scope("relationship", "sales")
def upd_sales(a, l, r, p, m, s, _):
    df = DATA.get("ts", pd.DataFrame())
    if df.empty:
        return html.Div("No data")
    df = filt(df, {"anchor": a, "lender": l, "role": r, "agent_email": p,
                   "sales_manager_email": m, "state": s})
    return build_sales_tables(df)


# ============ RSM ============
def build_rsm_tables(df):
    if df.empty:
        return html.Div("No data")
    df["plt_anchor"] = df["plt_anchor"].astype(str).str.lower()
    df["PLT_Anchor_Plus_Term_Loan"] = df["PLT_Anchor_Plus_Term_Loan"].astype(str).str.lower()
    plt_at = df[df["PLT_Anchor_Plus_Term_Loan"] == "true"]
    plt_a = df[df["plt_anchor"] == "true"]
    plt_na = df[(df["plt_anchor"] != "true") & (df["PLT_Anchor_Plus_Term_Loan"] != "true")]
    # Visual 3.2.1 | table | gpnbka | PLT Anchor + Term Loan AUM
    # Visual 3.2.2 | table | gpnbka | PLT Anchor + Term Loan deltas
    # Visual 3.2.3 | table | gpnbka | PLT Anchor AUM
    # Visual 3.2.4 | table | gpnbka | PLT Anchor deltas
    # Visual 3.2.5 | table | gpnbka | PLT Non Anchor AUM
    # Visual 3.2.6 | table | gpnbka | PLT Non Anchor deltas
    sections = []
    for cat_df, title in [(plt_at, "PLT Anchor + Term Loan"), (plt_a, "PLT Anchor"), (plt_na, "PLT Non Anchor")]:
        sections.append(html.Div(title, style={"fontSize": "13px", "margin": "24px 0 10px 4px",
                                                  "fontWeight": "600", "color": TEXT,
                                                  "borderLeft": f"3px solid {ACCENT}",
                                                  "paddingLeft": "10px"}))
        sections.append(html.Div([
            html.Div([pivot_table(cat_df, "sales_manager_email", "aum")],
                     style={"flex": "3", "minWidth": "500px", "overflow": "hidden"}),
            html.Div([delta_table(cat_df, "sales_manager_email")],
                     style={"flex": "2", "minWidth": "320px"}),
        ], className="mobile-visual-stack",
           style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "20px",
                  "alignItems": "flex-start", "background": CARD_BG,
                  "border": f"1px solid {BORDER}", "borderRadius": "6px",
                  "padding": "14px", "boxShadow": "0 2px 6px rgba(0,0,0,0.05)"}))
    return html.Div(sections)


def page_rsm():
    df = DATA.get("ts")
    if df is None or df.empty:
        return html.Div("No data")
    return html.Div([
        html.Div([slicer("Anchor", "ra", uvals(df, "anchor")),
                  slicer("State", "rs", uvals(df, "state")),
                  slicer("Lender", "rl", uvals(df, "lender")),
                  slicer("Regional Sales Manager", "rm", uvals(df, "sales_manager_email")),
                  slicer("Zonal Manager", "rz", uvals(df, "zonal_manager")),
                  clear_filters_button("rt-rsm-clear")],
                 style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginBottom": "20px"}),
        html.Div(id="rsm_tables", children=build_rsm_tables(df)),
        html.Div([download_button("dr", variant="primary")],
                 style={"textAlign": "right"}),
    ])


@callback(Output("rsm_tables", "children"),
          [Input("ra", "value"), Input("rs", "value"), Input("rl", "value"),
           Input("rm", "value"), Input("rz", "value"), Input("ver", "data")])
@with_visual_scope("relationship", "rsm")
def upd_rsm(a, s, l, m, z, _):
    df = DATA.get("ts", pd.DataFrame())
    if df.empty:
        return html.Div("No data")
    df = filt(df, {"anchor": a, "state": s, "lender": l, "sales_manager_email": m, "zonal_manager": z})
    return build_rsm_tables(df)


# ============ RAW DATA ============
def page_raw():
    df = DATA.get("raw")
    if df is None or df.empty:
        return html.Div("No data")
    return html.Div([
        html.Div([slicer("Anchor", "xa", uvals(df, "anchor")),
                  slicer("Lender", "xl", uvals(df, "lender")),
                  slicer("Sales POC", "xp", uvals(df, "agent_email")),
                  slicer("RSM", "xm", uvals(df, "sales_manager_email")),
                  slicer("State", "xs", uvals(df, "state")),
                  slicer("Line State", "xls", uvals(df, "line_state")),
                  slicer("DPD Bucket", "xd", uvals(df, "current_dpd_bucket")),
                  slicer("Dormancy", "xdd", uvals(df, "dd_flag")),
                  slicer("KAM", "xk", uvals(df, "kam")),
                  slicer("City", "xci", uvals(df, "city")),
                  clear_filters_button("rt-raw-clear")],
                 style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginBottom": "20px"}),
        html.Div(id="raw_info", style={"fontSize": "12px", "color": "#666", "marginBottom": "8px"}),
        html.Div(id="raw_tbl"),
        html.Div([download_button("dx", label="Export all filtered rows", variant="primary")],
                 style={"textAlign": "right"}),
    ])


@callback([Output("raw_info", "children"), Output("raw_tbl", "children")],
          [Input("xa", "value"), Input("xl", "value"), Input("xp", "value"),
           Input("xm", "value"), Input("xs", "value"), Input("xls", "value"),
           Input("xd", "value"), Input("xdd", "value"), Input("xk", "value"),
           Input("xci", "value"), Input("ver", "data")])
@with_visual_scope("relationship", "raw")
def upd_raw(a, l, p, m, s, ls, d, dd, k, c, _):
    df = DATA.get("raw", pd.DataFrame())
    if df.empty:
        return "No data", html.Div()
    df = filt(df, {"anchor": a, "lender": l, "agent_email": p, "sales_manager_email": m,
                   "state": s, "line_state": ls, "current_dpd_bucket": d, "dd_flag": dd, "kam": k, "city": c})
    show = df.head(500)
    info = f"Showing {len(show)} of {len(df)} records"
    display_cols = [x for x in df.columns if x not in ("check_date",)]
    # Visual 3.3.1 | table | gpnbka | Relationship raw data
    tbl = table_ui(show[display_cols], page_size=30, filterable=True,
                   downloadable=False, max_height=600, variant="primary")
    return info, tbl


# ============ VISITS ============
def page_visits():
    cv = DATA.get("cv")
    return html.Div([
        html.Div([slicer("Current Active", "va", uvals(cv, "current_active")),
                  slicer("Visited By", "vb", uvals(cv, "visited_by")),
                  slicer("Visit Reason", "vn", uvals(cv, "visit_reason")),
                  slicer("Manager Email", "vm", uvals(cv, "manager_email")),
                  slicer("Role", "vr", uvals(cv, "role")),
                  slicer("Anchor Name", "van", uvals(DATA.get("visits"), "anchor_name")),
                  slicer("Sprint", "vs", uvals(cv, "sprint")),
                  clear_filters_button("rt-visits-clear")],
                 style={"display": "flex", "flexWrap": "wrap", "gap": "12px", "marginBottom": "20px"}),
        html.Div(id="visits_content"),
        html.Div([download_button("dv", label="Export all filtered rows", variant="primary")],
                 style={"textAlign": "right"}),
    ])


@callback(Output("visits_content", "children"),
          [Input("va", "value"), Input("vb", "value"), Input("vn", "value"),
           Input("vm", "value"), Input("vr", "value"), Input("van", "value"),
           Input("vs", "value"), Input("ver", "data")])
@with_visual_scope("relationship", "visits")
def upd_visits(active, by, reason, mgr, role, anch, sprint, _):
    cv = DATA.get("cv", pd.DataFrame())
    cv_daily = DATA.get("cv_daily", pd.DataFrame())
    vdf = DATA.get("visits", pd.DataFrame())
    if cv.empty:
        return html.Div("No data")
    cv = filt(cv, {"current_active": active, "visited_by": by, "visit_reason": reason,
                   "manager_email": mgr, "role": role, "sprint": sprint})
    cv_daily = filt(cv_daily, {"visited_by": by})
    vdf = filt(vdf, {"visited_by": by, "visit_reason": reason, "manager_email": mgr,
                     "role": role, "anchor_name": anch})
    # Monthly pivot: visited_by x (month + sprint)
    cv_m = cv.copy()
    cv_m["visits"] = pd.to_numeric(cv_m["visits"], errors="coerce").fillna(0)
    cv_m["period"] = cv_m["check_month"].astype(str) + " " + cv_m["sprint"].astype(str)
    pv_month = cv_m.pivot_table(index="visited_by", columns="period", values="visits", aggfunc="sum").fillna(0)
    pv_month = pv_month.reindex(sorted(pv_month.columns), axis=1)
    # Total row
    pv_month.loc["Total"] = pv_month.sum()
    pv_month = pv_month.astype(int).reset_index()
    # Daily pivot
    sections = []
    if not cv_daily.empty:
        cv_daily["visits"] = pd.to_numeric(cv_daily["visits"], errors="coerce").fillna(0).astype(int)
        pv_daily = cv_daily.pivot_table(index="visited_by", columns="check_date",
                                         values="visits", aggfunc="sum").fillna(0).astype(int)
        pv_daily = pv_daily.reindex(sorted(pv_daily.columns), axis=1)
        pv_daily.loc["Total"] = pv_daily.sum()
        pv_daily = pv_daily.reset_index()
    else:
        pv_daily = pd.DataFrame()
    # Sprint color-coded header conditions for monthly pivot
    sprint_header_conds = []
    sprint_cell_conds = []
    for col in pv_month.columns:
        cstr = str(col)
        for sp, color in SPRINT_COLORS.items():
            if cstr.endswith(sp):
                sprint_cell_conds.append({"if": {"column_id": cstr}, "backgroundColor": color})
        for sp, hcolor in SPRINT_HEADER_COLORS.items():
            if cstr.endswith(sp):
                sprint_header_conds.append({"if": {"column_id": cstr, "header_index": 0},
                                            "backgroundColor": hcolor, "color": "#FFFFFF"})
    # Monthly table
    # Visual 3.4.1 | table | hmnkwl | Monthly visits
    # Visual 3.4.2 | table | hmnkwl | Daily visits
    sections.append(html.Div([
        html.Div([
            table_ui(pv_month, page_size=50, downloadable=False, max_height=400,
                     variant="primary", style_data_conditional=sprint_cell_conds,
                     style_header_conditional=sprint_header_conds),
        ], style={"flex": "3", "minWidth": "500px"}),
        html.Div([
            table_ui(pv_daily, page_size=50, downloadable=False, max_height=400,
                     variant="primary"),
        ], style={"flex": "2", "minWidth": "300px"}),
    ], className="mobile-visual-stack",
       style={"display": "flex", "gap": "16px", "flexWrap": "wrap", "marginBottom": "20px"}))
    # Raw visit details table
    disp = [x for x in ["visited_by", "role", "visit_date", "visit_month", "visit_sprint",
                         "visit_reason", "org_id", "org_name", "anchor_name", "rsm"] if x in vdf.columns]
    sections.append(html.Div("Raw Data", style={"fontSize": "12px", "margin": "20px 0 8px 4px",
                                                   "fontWeight": "600", "color": TEXT,
                                                   "borderLeft": f"3px solid {ACCENT}",
                                                   "paddingLeft": "10px"}))
    # Visual 3.4.3 | table | h2srrf | Raw visit details
    sections.append(table_ui(vdf[disp].head(200) if disp else pd.DataFrame(), page_size=20, filterable=True,
                             downloadable=False, max_height=400, variant="primary"))
    return html.Div(sections)


# ============ DOWNLOADS ============
@callback(Output("dl-s", "data"),
          Input("ds", "n_clicks"),
          [State("sa", "value"), State("sl", "value"), State("sr", "value"),
           State("sp", "value"), State("sm", "value"), State("ss", "value")],
          prevent_initial_call=True)
def do_dl_s(n, sa, sl, sr, sp, sm, ss):
    if not n or ctx.triggered_id != "ds":
        return no_update
    df = filt(DATA.get("ts", pd.DataFrame()),
              {"anchor": sa, "lender": sl, "role": sr, "agent_email": sp, "sales_manager_email": sm, "state": ss})
    return dcc.send_data_frame(df.to_csv, "sales_filtered.csv", index=False)


@callback(Output("dl-r", "data"),
          Input("dr", "n_clicks"),
          [State("ra", "value"), State("rs", "value"), State("rl", "value"),
           State("rm", "value"), State("rz", "value")],
          prevent_initial_call=True)
def do_dl_r(n, ra, rs, rl, rm_, rz):
    if not n or ctx.triggered_id != "dr":
        return no_update
    df = filt(DATA.get("ts", pd.DataFrame()),
              {"anchor": ra, "state": rs, "lender": rl, "sales_manager_email": rm_, "zonal_manager": rz})
    return dcc.send_data_frame(df.to_csv, "rsm_filtered.csv", index=False)


@callback(Output("dl-x", "data"),
          Input("dx", "n_clicks"),
          [State("xa", "value"), State("xl", "value"), State("xp", "value"),
           State("xm", "value"), State("xs", "value"), State("xls", "value"),
           State("xd", "value"), State("xdd", "value"), State("xk", "value"), State("xci", "value")],
          prevent_initial_call=True)
def do_dl_x(n, xa, xl, xp, xm, xs, xls, xd, xdd, xk, xci):
    if not n or ctx.triggered_id != "dx":
        return no_update
    df = filt(DATA.get("raw", pd.DataFrame()),
              {"anchor": xa, "lender": xl, "agent_email": xp, "sales_manager_email": xm,
               "state": xs, "line_state": xls, "current_dpd_bucket": xd, "dd_flag": xdd, "kam": xk, "city": xci})
    return dcc.send_data_frame(df.to_csv, "raw_filtered.csv", index=False)


@callback(Output("dl-v", "data"),
          Input("dv", "n_clicks"),
          [State("va", "value"), State("vb", "value"), State("vn", "value"),
           State("vm", "value"), State("vr", "value"), State("van", "value"),
           State("vs", "value")],
          prevent_initial_call=True)
def do_dl_v(n, va, vb, vn, vm, vr, van, vs):
    if not n or ctx.triggered_id != "dv":
        return no_update
    df = filt(DATA.get("visits", pd.DataFrame()),
              {"current_active": va, "visited_by": vb, "visit_reason": vn,
               "manager_email": vm, "role": vr, "anchor_name": van,
               "sprint": vs})
    return dcc.send_data_frame(df.to_csv, "visits_filtered.csv", index=False)
