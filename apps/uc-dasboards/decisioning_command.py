"""60-minute credit-decisioning command center backed by one probe."""
from __future__ import annotations

import threading
import time

import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from decisioning_metrics import apply_filters, month_dates, prepare, summarize
from shared import format_timestamp, run_query, track_tab_click
from ui import filter_ui, header_ui, kpi_card, tab_bar, table_ui, visual_card, visual_scope
from ui.config import load_json


CONFIG = load_json("decisioning_command.json")
PAGE = "decisioning_command"
TABS = [("snapshot", "View 1 · Eligibility Snapshot"), ("waterfall", "View 2 · Waterfall Funnel")]
_CACHE = None
_LOCK = threading.Lock()


def load():
    global _CACHE
    with _LOCK:
        if _CACHE and time.monotonic() - _CACHE[0] < CONFIG["cache_seconds"]:
            return _CACHE[1:]
        previous = _CACHE
        try:
            # This is deliberately the only source queried by this page.
            query = f"""
                SELECT
                    `credit_application_id` AS `application_id`,
                    `application_purpose`,
                    `new_limit`,
                    `uw_poc`,
                    `higher_approval_poc`,
                    `application_created_date`,
                    `incorporation_type`,
                    `UW_TAT_Mins` AS `tat_minutes`,
                    `created_at_decision` AS `decision_at`,
                    `high_ticket_flag`,
                    `deviation_flag`
                FROM {CONFIG['table']}
            """
            raw = run_query(query, context=PAGE, raise_on_error=True)
            frame = prepare(raw)
            updated = format_timestamp(frame["decision_at"].max()) if not frame.empty else "No decisions available"
            _CACHE = (time.monotonic(), frame, updated, "")
            return _CACHE[1:]
        except Exception as exc:
            if previous:
                return previous[1], previous[2], f"Refresh failed; showing previous snapshot: {exc}"
            return pd.DataFrame(), "Unavailable", f"Data load error: {exc}"


def _options(frame, column):
    if frame.empty or column not in frame:
        return []
    if column == "new_limit":
        return sorted(frame[column].dropna().unique().tolist())
    return sorted(frame[column].dropna().astype(str).unique(), key=str.casefold)


def _number(value):
    return "Unavailable" if value is None else f"{value:,.0f}"


def _percent(value):
    return "Unavailable" if value is None else f"{value:,.1f}%"


def _minutes(value):
    return "Unavailable" if value is None else f"{value:,.1f} min"


def _hours(value):
    return "Unavailable" if value is None else f"{value / 60:,.2f} hr"


def _current_month():
    return pd.Timestamp.now(tz="Asia/Kolkata").strftime("%Y-%m")


def _with_total(rows, count_columns, eligible_column, percentage_column):
    if not rows:
        return rows
    total = {"Date": "Total"}
    total.update({column: sum(row[column] for row in rows) for column in count_columns})
    eligible = total[eligible_column]
    total[percentage_column] = _percent(100 * total["Cases Under 60 Mins"] / eligible if eligible else None)
    return [*rows, total]


def render(tab, month, application_purpose, uw_poc, application_id, new_limit, higher_approval_poc):
    frame, updated, error = load()
    header = header_ui(CONFIG["title"], subtitle="Tracks the one-hour credit decision SLA.", updated_text=updated)
    if frame.empty:
        return header, html.Div(error or "No decisioning records available.", className="ui-state ui-state--empty")
    month = month or _current_month()
    filtered = apply_filters(frame, application_purpose, uw_poc, application_id, new_limit, higher_approval_poc)
    filtered = filtered[filtered["_date"].astype(str).str[:7].eq(month)]
    cards = []
    if error:
        cards.append(html.Div(error, className="ui-state ui-state--empty"))

    dates = month_dates(month, pd.Timestamp.now(tz="Asia/Kolkata").date())
    available_dates = sorted(filtered["_date"].dropna().unique())
    latest = filtered[filtered["_date"].eq(available_dates[-1])] if available_dates else filtered
    latest_metrics = summarize(latest, CONFIG["proprietorship_value"], CONFIG["threshold_minutes"])
    balance_tat = "No balance cases" if latest_metrics["balance"] == 0 else _hours(latest_metrics["balance_tat"])

    with visual_scope(PAGE, tab):
        if tab == "snapshot":
            date_label = f"APPLICATIONS CREATED ON {available_dates[-1]}" if available_dates else f"NO APPLICATIONS IN {month}"
            cards.append(html.Div(date_label, className="ui-section-title"))
            # Visual 8.1.1 | widget | hbcwzx | Eligible cases completed under 60 minutes
            cards.append(visual_card([
                kpi_card("% Eligible Cases Done Under 60 Mins", _percent(latest_metrics["rate_pct"]), track_visual=True),
                html.Div(
                    f'{_number(latest_metrics["under_60"])} of {_number(latest_metrics["eligible"])} eligible cases',
                    className="ui-page-subtitle",
                ),
            ]))
            cards.append(html.Div([
                # Visual 8.1.2 | widget | hbcwzx | Applications eligible
                kpi_card("% Applications Eligible", _percent(latest_metrics["eligible_pct"]), track_visual=True),
                # Visual 8.1.3 | widget | hbcwzx | Eligible P90 TAT
                kpi_card("90%ile TAT — Eligible", _hours(latest_metrics["eligible_tat"]), track_visual=True),
                # Visual 8.1.4 | widget | hbcwzx | Applications balance
                kpi_card("% Applications Balance", _percent(latest_metrics["balance_pct"]), track_visual=True),
                # Visual 8.1.5 | widget | hbcwzx | Balance P90 TAT
                kpi_card("90%ile TAT — Balance", balance_tat, track_visual=True),
            ], className="command-kpis"))

            rows = []
            for day in dates:
                metrics = summarize(filtered[filtered["_date"].eq(day)], CONFIG["proprietorship_value"], CONFIG["threshold_minutes"])
                rows.append({
                    "Date": str(day),
                    "Total Applications": metrics["total"],
                    "Total Eligible Cases": metrics["eligible"],
                    "Cases Under 60 Mins": metrics["under_60"],
                    "% Apps Done in 1 Hour": _percent(metrics["rate_pct"]),
                })
            # Visual 8.1.6 | table | hbcwzx | Selected-month application creation trend
            rows = _with_total(rows, ["Total Applications", "Total Eligible Cases", "Cases Under 60 Mins"],
                               "Total Eligible Cases", "% Apps Done in 1 Hour")
            cards.append(visual_card(table_ui(pd.DataFrame(rows), show_summary=True, max_height=400), title=f"Day-over-Day Trend — {month}"))
        else:
            count_rows, tat_rows = [], []
            labels = ["High Ticket (50L+)", "L4-L6 Deviation", "Non-Proprietorship"]
            for day in dates:
                metrics = summarize(filtered[filtered["_date"].eq(day)], CONFIG["proprietorship_value"], CONFIG["threshold_minutes"])
                count_row = {"Date": str(day), "Total Applications": metrics["total"]}
                tat_row = {"Date": str(day), "Total Applications": _minutes(metrics["total_tat"])}
                for index, label in enumerate(labels):
                    count_row[label] = metrics["stages"][index]
                    tat_row[label] = _minutes(metrics["stage_tats"][index])
                count_row["Final Eligibility"] = metrics["eligible"]
                tat_row["Final Eligibility"] = _minutes(metrics["eligible_tat"])
                count_row["Cases Under 60 Mins"] = metrics["under_60"]
                count_row["% Cases Under 60 Mins / Eligible"] = _percent(metrics["rate_pct"])
                tat_row["% Cases Under 60 Mins / Eligible"] = _percent(metrics["rate_pct"])
                count_rows.append(count_row)
                tat_rows.append(tat_row)
            # Visual 8.2.1 | table | hbcwzx | Sequential eligibility waterfall counts
            count_rows = _with_total(count_rows,
                                     ["Total Applications", *labels, "Final Eligibility", "Cases Under 60 Mins"],
                                     "Final Eligibility", "% Cases Under 60 Mins / Eligible")
            cards.append(visual_card(table_ui(pd.DataFrame(count_rows), show_summary=True, max_height=400), title="60-Min Decisioning Eligibility Waterfall — Count"))
            if tat_rows:
                period = filtered[filtered["_date"].isin(dates)]
                period_metrics = summarize(period, CONFIG["proprietorship_value"], CONFIG["threshold_minutes"])
                tat_total = {"Date": "Total", "Total Applications": _minutes(period_metrics["total_tat"])}
                for index, label in enumerate(labels):
                    tat_total[label] = _minutes(period_metrics["stage_tats"][index])
                tat_total["Final Eligibility"] = _minutes(period_metrics["eligible_tat"])
                tat_total["% Cases Under 60 Mins / Eligible"] = _percent(period_metrics["rate_pct"])
                tat_rows.append(tat_total)
            # Visual 8.2.2 | table | hbcwzx | Sequential eligibility waterfall P90 TAT
            cards.append(visual_card(table_ui(pd.DataFrame(tat_rows), show_summary=True, max_height=400), title="60-Min Decisioning Eligibility Waterfall — 90%ile TAT (Minutes)"))
            cards.append(html.Div("Exclusions apply sequentially: high ticket, L4-L6 deviation, then non-proprietorship. Each application is counted once.", className="ui-page-subtitle"))
    return header, html.Div(cards, style={"padding": "16px"})


def layout():
    frame, _, _ = load()
    month = _current_month()
    months = sorted({str(day)[:7] for day in frame["_date"].dropna()} | {month}, reverse=True) if not frame.empty else [month]
    return html.Div([
        dcc.Store(id=f"{PAGE}-active", data="snapshot"),
        dcc.Interval(id=f"{PAGE}-tick", interval=CONFIG["cache_seconds"] * 1000),
        html.Div(id=f"{PAGE}-header"),
        html.Div(html.Div([
            html.Label("Month", className="ui-filter__label"),
            dcc.Dropdown(
                id=f"{PAGE}-month",
                options=[{"label": item, "value": item} for item in months],
                value=month,
                clearable=False,
                searchable=False,
                className="ui-filter__control",
            ),
        ], className="ui-filter ui-filter--accent"), className="decisioning-month-filter"),
        html.Div([
            filter_ui("Application Purpose", f"{PAGE}-application-purpose", _options(frame, "application_purpose"), variant="accent"),
            filter_ui("UW POC", f"{PAGE}-uw-poc", _options(frame, "uw_poc"), variant="accent"),
            filter_ui("Application ID", f"{PAGE}-application-id", _options(frame, "application_id"), variant="accent"),
            filter_ui("Limit", f"{PAGE}-new-limit", _options(frame, "new_limit"), variant="accent"),
            filter_ui("Higher Approval Authority", f"{PAGE}-higher-approval-poc", _options(frame, "higher_approval_poc"), variant="accent"),
        ], className="decisioning-filters"),
        tab_bar(TABS, id_prefix=f"{PAGE}-tab-", active="snapshot"),
        html.Div(id=f"{PAGE}-content"),
    ])


@callback(
    Output(f"{PAGE}-active", "data"),
    [Input(f"{PAGE}-tab-{tab}", "n_clicks") for tab, _ in TABS] + [Input(f"{PAGE}-tab-mobile", "value")],
    State(f"{PAGE}-active", "data"),
    prevent_initial_call=True,
)
def choose_tab(*args):
    triggered = ctx.triggered_id
    selected = args[-2] if triggered == f"{PAGE}-tab-mobile" else str(triggered).removeprefix(f"{PAGE}-tab-")
    if selected not in dict(TABS) or selected == args[-1]:
        return no_update
    track_tab_click(PAGE, selected)
    return selected


@callback(
    [Output(f"{PAGE}-header", "children"), Output(f"{PAGE}-content", "children")]
    + [Output(f"{PAGE}-tab-{tab}", "className") for tab, _ in TABS],
    Input(f"{PAGE}-active", "data"),
    Input(f"{PAGE}-tick", "n_intervals"),
    Input(f"{PAGE}-month", "value"),
    Input(f"{PAGE}-application-purpose", "value"),
    Input(f"{PAGE}-uw-poc", "value"),
    Input(f"{PAGE}-application-id", "value"),
    Input(f"{PAGE}-new-limit", "value"),
    Input(f"{PAGE}-higher-approval-poc", "value"),
)
def update(tab, _, month, application_purpose, uw_poc, application_id, new_limit, higher_approval_poc):
    header, body = render(tab, month, application_purpose, uw_poc, application_id, new_limit, higher_approval_poc)
    return [header, body] + ["ui-tab active" if item == tab else "ui-tab" for item, _ in TABS]
