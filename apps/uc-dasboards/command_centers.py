"""Shared renderer for the 300-second invoice command center."""
import re
import time
import threading
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update
from shared import run_query, format_timestamp, track_tab_click
from ui import header_ui, visual_card, table_ui, kpi_card, tab_bar, visual_scope
from ui.config import load_json
from command_metrics import prepare, summarize

CONFIG = load_json("command_centers.json")
TABS = [("snapshot", "View 1 · Eligibility Snapshot"), ("waterfall", "View 2 · Waterfall Funnel")]
_CACHE = {}
_LOCK = threading.Lock()
INVOICE_COLUMNS = ["id", "latest_invoice_timestamp", "lender", "risky_customer", "invoice_amount_tag", "invoice_tat", "refresh_time"]


def load(page):
    cfg = CONFIG[page]
    with _LOCK:
        previous = _CACHE.get(page)
        if previous and time.monotonic() - previous[0] < CONFIG["cache_seconds"]:
            return previous[1:]
        try:
            columns = list(INVOICE_COLUMNS)
            columns += [cfg.get(key) for key in ("id_column", "date_column", "updated_column", "overall_column")]
            columns.append(cfg.get("tat_column"))
            columns += [r.get("column") for r in cfg["exclusions"]]
            columns += [r.get("column") for r in cfg.get("row_filters", [])]
            columns = list(dict.fromkeys(c for c in columns if c))
            for name in [*cfg["table"].split("."), *columns]:
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    raise ValueError("Invalid configured SQL identifier")
            date_col = cfg["date_column"]
            query = (
                "SELECT " + ", ".join(f"`{c}`" for c in columns) + f" FROM {cfg['table']} "
                f"WHERE try_cast(substring(`{date_col}`, 1, 10) AS DATE) >= "
                f"date_sub(current_date(), {int(CONFIG['days']) + 2})"
            )
            raw = run_query(query, context=page, raise_on_error=True)
            frame = prepare(raw, cfg)
            updated_col = cfg["updated_column"]
            updated = format_timestamp(raw[updated_col].max()) if updated_col in raw and not raw.empty else "No refresh timestamp"
            result = (frame, updated, "")
            _CACHE[page] = (time.monotonic(), *result)
            return result
        except Exception as exc:
            if previous:
                return previous[1], previous[2], f"Refresh failed; showing previous snapshot: {exc}"
            return pd.DataFrame(), "Unavailable", f"Data load error: {exc}"


def value(number, suffix=""):
    return "Unavailable" if number is None else f"{number:,.1f}{suffix}"


def duration(number):
    if number is None:
        return "Unavailable"
    if number < 600:
        return f"{number:,.0f} sec"
    if number < 7200:
        return f"{number / 60:,.1f} min"
    if number < 172800:
        return f"{number / 3600:,.1f} hr"
    return f"{number / 86400:,.1f} days"


def render(page, tab):
    cfg = CONFIG[page]
    frame, updated, error = load(page)
    end = pd.Timestamp.now(tz="Asia/Kolkata").date() - pd.Timedelta(days=1)
    dates = pd.date_range(end=end, periods=CONFIG["days"]).date
    def daily(day):
        if "_date" not in frame:
            return None
        return summarize(frame[frame["_date"].eq(day)], cfg)
    results = [(day, daily(day)) for day in dates]
    latest = results[-1][1]
    header = header_ui(cfg["title"], updated_text=updated)
    cards = []
    if error:
        cards.append(html.Div(error, className="ui-state ui-state--empty"))
    with visual_scope(page, tab):
        if tab == "snapshot":
            cards.append(html.Div(f"YESTERDAY · {end:%Y-%m-%d}", className="ui-section-title"))
            metric = value(latest["rate_pct"] if latest else None, "%")
            target = cfg.get("target_percent")
            key_metric = [kpi_card(cfg["headline_label"], metric, track_visual=True)]
            if target:
                key_metric.append(html.Div(f"Target: {target}%", className="ui-page-subtitle"))
            cards.append(visual_card(key_metric))
            tiles = []
            for label, key, is_duration in [(cfg["eligible_widget_label"], "eligible_pct", False), ("90%ile TAT - Eligible", "eligible_tat", True), (cfg["balance_widget_label"], "balance_pct", False), ("90%ile TAT - Balance", "balance_tat", True)]:
                number = latest[key] if latest else None
                tiles.append(kpi_card(label, duration(number) if is_duration else value(number, "%"), track_visual=True))
            cards.append(html.Div(tiles, className="command-kpis"))
            rows = []
            for day, metrics in results:
                rows.append({"Date": str(day), cfg["total_column"]: metrics["total"] if metrics else 0, cfg["rate_column"]: value(metrics["rate_pct"] if metrics else None, "%"), "% Eligible": value(metrics["eligible_pct"] if metrics else None, "%"), "TAT Eligible": duration(metrics["eligible_tat"] if metrics else None), "% Balance": value(metrics["balance_pct"] if metrics else None, "%"), "TAT Balance": duration(metrics["balance_tat"] if metrics else None), "Overall TAT": duration(metrics["overall"] if metrics else None)})
            cards.append(visual_card(table_ui(pd.DataFrame(rows), show_summary=False), title="Day-over-Day Trend - Last 7 Days"))
        else:
            count_rows = []
            tat_rows = []
            for day, metrics in results:
                count_row = {"Date": str(day), cfg["total_column"]: metrics["total"] if metrics else 0}
                tat_row = {"Date": str(day), cfg["total_column"]: duration(metrics["total_tat"] if metrics else None)}
                for i, rule in enumerate(cfg["exclusions"]):
                    count = metrics["stages"][i] if metrics else None
                    count_row[rule["label"]] = count if count is not None else 0
                    tat_row[rule["label"]] = duration(metrics["stage_tats"][i] if metrics else None)
                count_row[cfg["net_column"]] = metrics["eligible"] if metrics and metrics["eligible"] is not None else 0
                count_row["% Eligible"] = value(metrics["eligible_pct"] if metrics else None, "%")
                tat_row[cfg["net_column"]] = duration(metrics["eligible_tat"] if metrics else None)
                tat_row["% Eligible"] = value(metrics["eligible_pct"] if metrics else None, "%")
                count_rows.append(count_row)
                tat_rows.append(tat_row)
            cards.append(visual_card(table_ui(pd.DataFrame(count_rows), show_summary=False), title=f"{cfg['waterfall_title']} - Count"))
            cards.append(visual_card(table_ui(pd.DataFrame(tat_rows), show_summary=False), title=f"{cfg['waterfall_title']} - 90% TAT"))
            cards.append(html.Div("Exclusions apply sequentially from left to right; each record is subtracted once.", className="ui-page-subtitle"))
    return header, html.Div(cards, style={"padding": "16px"})


def layout(page):
    return html.Div([
        dcc.Store(id=f"{page}-active", data="snapshot"),
        dcc.Interval(id=f"{page}-tick", interval=CONFIG["cache_seconds"] * 1000),
        html.Div(id=f"{page}-header"),
        tab_bar(TABS, id_prefix=f"{page}-tab-", active="snapshot"),
        html.Div(id=f"{page}-content"),
    ])


def register(page):
    @callback(Output(f"{page}-active", "data"), [Input(f"{page}-tab-{t}", "n_clicks") for t, _ in TABS] + [Input(f"{page}-tab-mobile", "value")], State(f"{page}-active", "data"), prevent_initial_call=True)
    def choose(*args):
        tid = ctx.triggered_id
        selected = args[-2] if tid == f"{page}-tab-mobile" else str(tid).removeprefix(f"{page}-tab-")
        if selected not in dict(TABS) or selected == args[-1]:
            return no_update
        track_tab_click(page, selected)
        return selected

    @callback([Output(f"{page}-header", "children"), Output(f"{page}-content", "children")] + [Output(f"{page}-tab-{t}", "className") for t, _ in TABS], Input(f"{page}-active", "data"), Input(f"{page}-tick", "n_intervals"))
    def update(tab, _):
        header, body = render(page, tab)
        return [header, body] + ["ui-tab active" if t == tab else "ui-tab" for t, _ in TABS]


register("invoice_command")
