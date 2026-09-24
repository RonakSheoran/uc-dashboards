"""LT Sales LMS — three-page dashboard from the LT Sales Power BI model."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from shared import filter_frame, format_timestamp, run_queries, run_query, track_tab_click, unique_values
from ui import (
    NAVIGATION,
    clear_filters_button,
    filter_ui,
    full_export_controls,
    header_ui,
    register_filter_reset,
    tab_bar,
    table_ui,
    visual_card,
    with_visual_scope,
)


SCHEMA = os.getenv("LT_SALES_SCHEMA", "hive_metastore.probes")
LEAD_TABLE = f"{SCHEMA}.lead_details_ref_fvvs4w"
DEFAULT_TAB = "daily-performance"
TAB_LIST = [
    (tab["id"], tab["label"])
    for tab in sorted(NAVIGATION["subpages"]["lt_sales"], key=lambda item: item.get("order", 0))
]

LEAD_COLUMNS = [
    "lead_id", "lead_name", "key_person", "mobile", "Anchor", "anchor_org_id",
    "anchor_poc", "anchor_poc_id", "officer", "officer_role", "reporting_manager",
    "state", "city", "lead_bd", "lead_source_bucket", "lead_sourced_by",
    "lead_upload_date", "lead_upload_month", "task_completion_date",
    "task_completion_time_stamp", "credit_application_id", "current_lead_state",
    "from_state", "to_state", "reason", "comment", "nextActionDate",
    "interaction_recency", "followup_breach", "anchor_program_id", "priority",
    "secondaryDisposition", "uc_score", "uc_score_bucket", "derived_limit",
    "gst_number", "current_application_state", "application_created_at",
    "application_creation_month", "duration",
]

LEAD_FILTERS = [
    ("lead_upload_month", "Upload Month"), ("officer", "Officer"),
    ("reporting_manager", "Manager"), ("officer_role", "Role"),
    ("Anchor", "Anchor"), ("anchor_org_id", "Anchor Org ID"),
    ("anchor_program_id", "Program ID"), ("anchor_poc", "Anchor POC"),
    ("lead_bd", "Lead BD"), ("state", "State"), ("city", "City"),
    ("current_lead_state", "Lead State"),
    ("current_application_state", "App State"),
    ("lead_source_bucket", "Lead Source"), ("lead_sourced_by", "Lead Sourced By"),
    ("uc_score_bucket", "UC Score Bucket"), ("followup_breach", "Followup Breach"),
    ("interaction_recency", "Interaction Recency"), ("priority", "Priority"),
    ("secondaryDisposition", "Secondary Disposition"),
    ("lead_upload_date", "Lead Upload Date"),
    ("task_completion_date", "Task Completion Date"),
    ("application_created_at", "Application Created At"),
]
LEAD_TEXT_FILTERS = [
    ("lead_id", "Lead ID"), ("mobile", "Mobile"),
    ("lead_name", "Lead Name"), ("credit_application_id", "App ID"),
]
LEAD_DISPLAY_COLUMNS = [
    "mobile", "lead_id", "lead_name", "key_person", "Anchor", "anchor_org_id",
    "lead_bd", "lead_upload_date", "derived_limit", "uc_score", "uc_score_bucket",
    "officer", "officer_role", "reporting_manager", "gst_number", "anchor_poc",
    "anchor_poc_id", "city", "state", "task_completion_time_stamp",
    "task_completion_date", "current_lead_state", "from_state", "to_state",
    "secondaryDisposition", "reason", "comment", "nextActionDate", "duration",
    "interaction_recency", "lead_sourced_by", "lead_source_bucket", "priority",
    "credit_application_id", "current_application_state", "application_created_at",
    "application_creation_month",
]

ANCHOR_FILTERS = [
    ("current_lead_state", "Lead State"), ("lead_source_bucket", "Lead Source"),
    ("Anchor", "Anchor"), ("officer", "Officer"),
    ("followup_breach", "Followup Breach"), ("lead_upload_month", "Upload Month"),
    ("officer_role", "Role"), ("current_application_state", "App State"),
    ("anchor_program_id", "Program ID"), ("lead_bd", "Lead BD"),
    ("task_completion_date", "Task Completion Date"),
    ("reporting_manager", "Manager"), ("lead_upload_date", "Lead Upload Date"),
]

DAILY_FILTERS = [
    ("officer_role", "Role"), ("officer", "Officer"),
    ("reporting_manager", "Manager"),
    ("followup_breach", "Followup Breach"), ("Date", "Date"),
]

LEAD_FILTER_IDS = [f"lts-li-{column}" for column, _ in LEAD_FILTERS]
LEAD_TEXT_IDS = [f"lts-li-text-{column}" for column, _ in LEAD_TEXT_FILTERS]
ANCHOR_FILTER_IDS = [f"lts-as-{column}" for column, _ in ANCHOR_FILTERS]
DAILY_FILTER_IDS = [f"lts-dp-{column}" for column, _ in DAILY_FILTERS]
register_filter_reset("lts-li-clear", LEAD_FILTER_IDS + LEAD_TEXT_IDS)
register_filter_reset("lts-as-clear", ANCHOR_FILTER_IDS)
register_filter_reset("lts-dp-clear", DAILY_FILTER_IDS)

LEADS = pd.DataFrame()
LEADS_ERROR = ""
DAILY = {}
DAILY_ERROR = ""
LEADS_LOADED_AT = "Source timestamp unavailable"


def load_leads() -> None:
    global LEADS, LEADS_ERROR, LEADS_LOADED_AT
    try:
        loaded = run_query(
            f"SELECT {', '.join(LEAD_COLUMNS)} FROM {LEAD_TABLE}",
            context="lt-sales:fvvs4w", raise_on_error=True,
        )
        LEADS = loaded
        LEADS_ERROR = ""
        LEADS_LOADED_AT = format_timestamp(pd.Timestamp.now(tz="Asia/Kolkata"))
        return True
    except Exception as exc:
        LEADS_ERROR = str(exc)
        print(f"[lt_sales] lead load failed: {exc}", file=sys.stderr)
        return False


def load_daily() -> None:
    global DAILY, DAILY_ERROR
    queries = {
        "officers": f"SELECT officer, reporting_manager, officer_role FROM {SCHEMA}.all_officers_crm_hgxh5i",
        "attendance": f"SELECT user_email, attendance_date, attendance_flag, sprint FROM {SCHEMA}.app_attendance_ilvfwm",
        "calling": f"SELECT officer, call_date, all_calls_dialed, all_calls_connected, all_talktime, customer_calls_dialed, customer_calls_connected, customer_talktime, sprint FROM {SCHEMA}.calling_data_agg_ifvotb",
        "funnel": f"SELECT officer, manager, check_date, applications_created, risk_logins_done, approvals_done, activations_done, rejections, cancellations, dd_count, sprint FROM {SCHEMA}.daily_sales_funnel_wmbygc",
        "breach": f"SELECT officer, Anchor, lead_id, lead_name, lead_bd, followup_breach, lead_upload_date, nextActionDate, latest_updated_at FROM {SCHEMA}.followup_breach_report_xo5ozz",
    }
    try:
        loaded = run_queries(queries, context="lt-sales", raise_on_error=True)
        DAILY = loaded
        DAILY_ERROR = ""
        return True
    except Exception as exc:
        DAILY_ERROR = str(exc)
        print(f"[lt_sales] daily load failed: {exc}", file=sys.stderr)
        return False


def refresh_data():
    """Refresh both LT Sales snapshots; each retains its last good data on failure."""
    leads_ok = load_leads()
    daily_ok = load_daily()
    return leads_ok and daily_ok


load_leads()
load_daily()


def _options(frame: pd.DataFrame, column: str) -> list:
    return unique_values(frame, column, stringify=True)


def _filters(frame: pd.DataFrame, definitions, prefix: str):
    return [
        filter_ui(label, f"{prefix}{column}", _options(frame, column), multi=True, variant="accent")
        for column, label in definitions if column in frame.columns
    ]


def _text_filter(column: str, label: str):
    return html.Div([
        html.Label(label, className="ui-filter__label"),
        dcc.Input(id=f"lts-li-text-{column}", type="text", debounce=True,
                  placeholder=f"Search {label}", className="ui-filter-text"),
    ], className="ui-filter")


def _apply(frame: pd.DataFrame, definitions, selections) -> pd.DataFrame:
    filters = {column: selected for (column, _), selected in zip(definitions, selections) if selected}
    return filter_frame(frame, filters, stringify=True)


def _filtered_leads(dropdown_values, text_values) -> pd.DataFrame:
    filtered = _apply(LEADS, LEAD_FILTERS, dropdown_values)
    for (column, _label), value in zip(LEAD_TEXT_FILTERS, text_values):
        if value and column in filtered.columns:
            filtered = filtered.loc[
                filtered[column].astype(str).str.contains(
                    str(value), case=False, regex=False, na=False
                )
            ]
    return filtered


@with_visual_scope("lt_sales", "lead-interaction")
def _lead_visual(frame: pd.DataFrame):
    columns = [column for column in LEAD_DISPLAY_COLUMNS if column in frame.columns]
    visible = frame[columns].head(500).copy() if columns else pd.DataFrame()
    # Visual 5.1.1 | table | fvvs4w | Lead Interaction Detail
    return visual_card(
        table_ui(visible, component_id="lts-li-table", max_height=520,
                 filterable=True, downloadable=False),
        title="Lead Interaction Detail",
    )


def _lead_page():
    if LEADS_ERROR and LEADS.empty:
        return html.Div(f"Data load error: {LEADS_ERROR}", className="ui-state ui-state--error")
    controls = [_text_filter(column, label) for column, label in LEAD_TEXT_FILTERS]
    controls.extend(_filters(LEADS, LEAD_FILTERS, "lts-li-"))
    controls.extend([
        clear_filters_button("lts-li-clear"),
    ])
    return html.Div([
        header_ui("Lead Interaction Summary", subtitle="LT Sales LMS",
                  updated_text=LEADS_LOADED_AT, badge_id="lts-li-updated"),
        visual_card(html.Div(controls, className="ui-filter-row"), title="Filters"),
        full_export_controls("lts-li-export-all", "lts-li-download-all"),
        html.Div(_lead_visual(LEADS), id="lts-li-content"),
        html.Div(f"Showing first {min(len(LEADS), 500):,} of {len(LEADS):,} rows",
                 id="lts-li-status", className="ui-page-subtitle"),
    ], className="ui-page-body")


def compute_anchor_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "Anchor" not in frame.columns:
        return pd.DataFrame()
    latest = frame.loc[frame["interaction_recency"] == "Latest Interaction"] if "interaction_recency" in frame.columns else frame
    rows = []
    states = [
        ("Reattempt", "% Reattempt"), ("Under-discussion", "% Under Discussion"),
        ("Requesting-anchor-callback", "% Anchor Callback"),
        ("Potential-not-interested", "% Potential Not Int."),
        ("Not-interested", "% Not Interested"), ("Not-eligible", "% Not Eligible"),
        ("Duplicate-lead", "% Duplicate Lead"), ("Pre-risk-login", "% Pre-risk Login"),
        ("Risk-login-done", "% Risk Login Done"),
        ("Application-cancelled", "% App Cancelled"),
        ("Application-rejected", "% App Rejected"),
        ("Closed-by-system", "% Closed by System"),
    ]
    for anchor, group in frame.groupby("Anchor", dropna=False):
        total = group["lead_id"].nunique()
        current = latest.loc[latest["Anchor"] == anchor]
        attempted = current.loc[current["to_state"].notna() & current["to_state"].ne("") & current["to_state"].ne("Not-Picked"), "lead_id"].nunique()
        row = {"Anchor": anchor, "Total Leads": total, "Leads Attempted": attempted,
               "% Attempted": f"{attempted / total:.2%}" if total else "0.00%"}
        for state, label in states:
            count = current.loc[current["to_state"] == state, "lead_id"].nunique()
            row[label] = f"{count / attempted:.2%}" if attempted else "0.00%"
        rows.append(row)
    return pd.DataFrame(rows).sort_values("Total Leads", ascending=False, kind="stable")


def _anchor_with_total(frame: pd.DataFrame) -> pd.DataFrame:
    result = compute_anchor_summary(frame)
    if frame.empty:
        return result
    total_frame = frame.copy()
    total_frame["Anchor"] = "Total"
    return pd.concat([result, compute_anchor_summary(total_frame)], ignore_index=True)


@with_visual_scope("lt_sales", "anchor-summary")
def _anchor_visual(frame: pd.DataFrame):
    summary = _anchor_with_total(frame)
    # Visual 5.2.1 | table | fvvs4w | Anchor Level Summary
    return visual_card(
        table_ui(summary, component_id="lts-as-table", max_height=560),
        title="Anchor Level Summary",
    )


def _anchor_page():
    controls = _filters(LEADS, ANCHOR_FILTERS, "lts-as-")
    controls.extend([
        clear_filters_button("lts-as-clear"),
    ])
    return html.Div([
        header_ui("Anchor Level Summary", subtitle="LT Sales LMS",
                  updated_text=LEADS_LOADED_AT, badge_id="lts-as-updated"),
        visual_card(html.Div(controls, className="ui-filter-row"), title="Filters"),
        html.Div(_anchor_visual(LEADS), id="lts-as-content"),
        html.Div(f"Loaded {len(LEADS):,} rows", id="lts-as-status", className="ui-page-subtitle"),
    ], className="ui-page-body")


DATE_COLUMNS = {"attendance": "attendance_date", "calling": "call_date", "funnel": "check_date", "breach": "nextActionDate"}


def _daily_date_options() -> list[str]:
    values = set()
    for key, column in DATE_COLUMNS.items():
        frame = DAILY.get(key, pd.DataFrame())
        if not frame.empty and column in frame.columns:
            dates = pd.to_datetime(frame[column], errors="coerce").dropna().dt.strftime("%Y-%m-%d")
            values.update(dates.tolist())
    return sorted(values)


def _filter_daily(selections) -> dict[str, pd.DataFrame]:
    role, officer, manager, breach_flag, selected_dates = selections
    officers = DAILY.get("officers", pd.DataFrame()).copy()
    officers = filter_frame(officers, {
        "officer_role": role, "officer": officer, "reporting_manager": manager,
    }, stringify=True)
    valid = set(officers.get("officer", pd.Series(dtype=object)).astype(str))
    output = {"officers": officers}
    for key, frame in DAILY.items():
        if key == "officers":
            continue
        current = frame.copy()
        actor = "user_email" if "user_email" in current.columns else "officer" if "officer" in current.columns else None
        if actor and (role or officer or manager):
            current = current.loc[current[actor].astype(str).isin(valid)]
        if key == "breach" and breach_flag:
            current = filter_frame(current, {"followup_breach": breach_flag}, stringify=True)
        if selected_dates and key in DATE_COLUMNS and DATE_COLUMNS[key] in current.columns:
            allowed = set(pd.to_datetime(selected_dates, errors="coerce").date)
            actual = pd.to_datetime(current[DATE_COLUMNS[key]], errors="coerce").dt.date
            current = current.loc[actual.isin(allowed)]
        output[key] = current
    return output


def _officer_grid(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    officers = data.get("officers", pd.DataFrame())
    if officers.empty:
        return pd.DataFrame()
    result = officers[["officer", "reporting_manager"]].drop_duplicates().copy()
    attendance = data.get("attendance", pd.DataFrame())
    if not attendance.empty:
        agg = attendance.groupby("user_email")["attendance_flag"].sum().rename("Attendance").reset_index().rename(columns={"user_email": "officer"})
        result = result.merge(agg, on="officer", how="left")
    calling = data.get("calling", pd.DataFrame())
    if not calling.empty:
        agg = calling.groupby("officer")[["all_calls_dialed", "all_calls_connected", "all_talktime"]].sum().reset_index()
        result = result.merge(agg, on="officer", how="left")
    funnel = data.get("funnel", pd.DataFrame())
    if not funnel.empty:
        columns = ["applications_created", "risk_logins_done", "approvals_done", "activations_done", "rejections", "cancellations", "dd_count"]
        agg = funnel.groupby("officer")[[column for column in columns if column in funnel.columns]].sum().reset_index()
        result = result.merge(agg, on="officer", how="left")
    breach = data.get("breach", pd.DataFrame())
    if not breach.empty:
        status = breach.groupby(["officer", "followup_breach"]).size().unstack(fill_value=0).rename(columns={"breached": "Breached Followups", "not-breached": "Followups completed"})
        for column in ("Breached Followups", "Followups completed"):
            if column not in status.columns:
                status[column] = 0
        status["Followups required"] = breach.groupby("officer")["lead_id"].count()
        result = result.merge(status.reset_index(), on="officer", how="left")
    result = result.fillna(0)
    columns = ["officer", "reporting_manager", "Attendance", "all_calls_dialed", "all_calls_connected", "all_talktime", "Followups required", "Breached Followups", "Followups completed", "applications_created", "risk_logins_done", "approvals_done", "activations_done"]
    return result[[column for column in columns if column in result.columns]].sort_values(["reporting_manager", "officer"], kind="stable")


def _breach_detail(data: dict[str, pd.DataFrame], *, limit: int | None = None) -> pd.DataFrame:
    breach = data.get("breach", pd.DataFrame())
    if breach.empty:
        return pd.DataFrame()
    columns = [column for column in ["officer", "lead_id", "lead_name", "Anchor", "lead_bd", "nextActionDate", "followup_breach", "lead_upload_date"] if column in breach.columns]
    detail = breach[columns].copy().rename(columns={"nextActionDate": "Followup Date", "followup_breach": "followup_breach_flag"})
    officers = data.get("officers", pd.DataFrame())
    if not officers.empty:
        detail = detail.merge(officers[["officer", "reporting_manager"]].drop_duplicates(), on="officer", how="left")
    detail = detail.sort_values("followup_breach_flag", kind="stable")
    return detail.head(limit) if limit is not None else detail


def _daily_updated() -> str:
    breach = DAILY.get("breach", pd.DataFrame())
    if breach.empty or "latest_updated_at" not in breach.columns:
        return "Source timestamp unavailable"
    values = pd.to_datetime(breach["latest_updated_at"], errors="coerce").dropna()
    return format_timestamp(values.max()) if not values.empty else "Source timestamp unavailable"


@with_visual_scope("lt_sales", "daily-performance")
def _daily_visuals(data: dict[str, pd.DataFrame]):
    officer = _officer_grid(data)
    breach = _breach_detail(data, limit=500)
    return html.Div([
        # Visual 5.3.1 | table | hgxh5i | Officer Performance Summary
        visual_card(table_ui(officer, component_id="lts-dp-officer", max_height=420),
                    title="Officer Performance Summary"),
        # Visual 5.3.2 | table | xo5ozz | Followup Breach Detail
        visual_card(table_ui(breach, component_id="lts-dp-breach", max_height=360,
                             filterable=True, downloadable=False),
                    title="Followup Breach Detail"),
    ])


def _daily_page():
    officers = DAILY.get("officers", pd.DataFrame())
    breach = DAILY.get("breach", pd.DataFrame())
    controls = _filters(officers, DAILY_FILTERS[:3], "lts-dp-")
    controls.append(filter_ui("Followup Breach", "lts-dp-followup_breach", _options(breach, "followup_breach"), multi=True, variant="accent"))
    controls.append(filter_ui("Date", "lts-dp-Date", _daily_date_options(), multi=True, variant="accent"))
    controls.extend([
        clear_filters_button("lts-dp-clear"),
    ])
    return html.Div([
        header_ui("Daily Performance", subtitle="LT Sales LMS", updated_text=_daily_updated(), badge_id="lts-dp-updated"),
        visual_card(html.Div(controls, className="ui-filter-row"), title="Filters"),
        full_export_controls("lts-dp-export-all", "lts-dp-download-all"),
        html.Div(_daily_visuals(DAILY), id="lts-dp-content"),
        html.Div("", id="lts-dp-status", className="ui-page-subtitle"),
    ], className="ui-page-body")


def layout():
    return html.Div([
        dcc.Store(id="lts-active-tab", data=DEFAULT_TAB),
        html.Div(tab_bar(TAB_LIST, id_prefix="lts-tab-", active=DEFAULT_TAB), id="lts-tabs"),
        html.Div(id="lts-page-content"),
    ], style={"background": "#f0f0f3", "minHeight": "100vh"})


@callback(Output("lts-active-tab", "data"),
          [Input(f"lts-tab-{tab_id}", "n_clicks") for tab_id, _ in TAB_LIST]
          + [Input("lts-tab-mobile", "value")],
          prevent_initial_call=True)
def select_tab(*values):
    if ctx.triggered_id == "lts-tab-mobile":
        selected = values[-1] or no_update
    else:
        selected = str(ctx.triggered_id).removeprefix("lts-tab-") if ctx.triggered_id else no_update
    if selected is not no_update:
        track_tab_click("lt_sales", selected)
    return selected


@callback([Output("lts-tabs", "children"), Output("lts-page-content", "children")],
          Input("lts-active-tab", "data"))
def render_tab(active):
    pages = {"lead-interaction": _lead_page, "anchor-summary": _anchor_page,
             "daily-performance": _daily_page}
    selected = active if active in pages else DEFAULT_TAB
    return tab_bar(TAB_LIST, id_prefix="lts-tab-", active=selected), pages[selected]()


@callback(
    [Output("lts-li-content", "children"), Output("lts-li-updated", "children"),
     Output("lts-li-status", "children")]
    + [Output(component_id, "options") for component_id in LEAD_FILTER_IDS],
    [Input(component_id, "value") for component_id in LEAD_FILTER_IDS + LEAD_TEXT_IDS],
    prevent_initial_call=True,
)
def update_lead_page(*args):
    dropdown_values = args[:len(LEAD_FILTERS)]
    text_values = args[len(LEAD_FILTERS):len(LEAD_FILTERS) + len(LEAD_TEXT_FILTERS)]
    filtered = _filtered_leads(dropdown_values, text_values)
    options = [[{"label": value, "value": value} for value in _options(LEADS, column)] for column, _ in LEAD_FILTERS]
    status = f"Showing first {min(len(filtered), 500):,} of {len(filtered):,} filtered rows"
    return _lead_visual(filtered), LEADS_LOADED_AT, status, *options


@callback(
    Output("lts-li-download-all", "data"),
    Input("lts-li-export-all", "n_clicks"),
    [State(component_id, "value") for component_id in LEAD_FILTER_IDS + LEAD_TEXT_IDS],
    prevent_initial_call=True,
)
def export_all_leads(_n_clicks, *values):
    dropdown_values = values[:len(LEAD_FILTERS)]
    text_values = values[len(LEAD_FILTERS):len(LEAD_FILTERS) + len(LEAD_TEXT_FILTERS)]
    filtered = _filtered_leads(dropdown_values, text_values)
    columns = [column for column in LEAD_DISPLAY_COLUMNS if column in filtered.columns]
    if filtered.empty or not columns:
        return no_update
    return dcc.send_data_frame(
        filtered[columns].to_csv,
        "lead_interaction_filtered.csv",
        index=False,
    )


@callback(
    [Output("lts-as-content", "children"), Output("lts-as-updated", "children"),
     Output("lts-as-status", "children")]
    + [Output(component_id, "options") for component_id in ANCHOR_FILTER_IDS],
    [Input(component_id, "value") for component_id in ANCHOR_FILTER_IDS],
    prevent_initial_call=True,
)
def update_anchor_page(*args):
    filtered = _apply(LEADS, ANCHOR_FILTERS, args[:len(ANCHOR_FILTERS)])
    options = [[{"label": value, "value": value} for value in _options(LEADS, column)] for column, _ in ANCHOR_FILTERS]
    return _anchor_visual(filtered), LEADS_LOADED_AT, f"Loaded {len(filtered):,} filtered rows", *options


@callback(
    [Output("lts-dp-content", "children"), Output("lts-dp-updated", "children"),
     Output("lts-dp-status", "children")],
    [Input(component_id, "value") for component_id in DAILY_FILTER_IDS],
    prevent_initial_call=True,
)
def update_daily_page(*args):
    filtered = _filter_daily(args[:len(DAILY_FILTERS)])
    breach_count = len(filtered.get("breach", pd.DataFrame()))
    return _daily_visuals(filtered), _daily_updated(), f"{breach_count:,} followup rows after filters"


@callback(
    Output("lts-dp-download-all", "data"),
    Input("lts-dp-export-all", "n_clicks"),
    [State(component_id, "value") for component_id in DAILY_FILTER_IDS],
    prevent_initial_call=True,
)
def export_all_breach_rows(_n_clicks, *values):
    filtered = _filter_daily(values[:len(DAILY_FILTERS)])
    export = _breach_detail(filtered)
    if export.empty:
        return no_update
    return dcc.send_data_frame(
        export.to_csv,
        "followup_breach_filtered.csv",
        index=False,
    )
