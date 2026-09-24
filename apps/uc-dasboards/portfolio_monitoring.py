"""Portfolio Monitoring — JSON-led recreation of the supplied Power BI template."""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from shared import filter_frame, format_timestamp, make_financial_pivot, run_query, track_tab_click, unique_values
from ui import (
    NAVIGATION, clear_filters_button, filter_ui, full_export_controls, header_ui,
    register_filter_reset, tab_bar, table_ui, visual_card, with_visual_scope,
)
from ui.config import load_json


CONFIG = load_json("portfolio_monitoring.json")
SCHEMA = os.getenv("PORTFOLIO_SCHEMA", "hive_metastore.probes")
TABLES = {
    "portfolio": f"{SCHEMA}.portfolio_monitoring_i4dzcz",
    "ns_em": f"{SCHEMA}.ns_em_cases_f7cbqv",
    "potential": f"{SCHEMA}.potential_ns_em_g4nqsv",
    "enhancement": f"{SCHEMA}.limit_enhancement_analysis_wtyaum",
}
TABS = sorted(NAVIGATION["subpages"]["portfolio"], key=lambda item: item.get("order", 0))
TAB_LIST = [(item["id"], item["label"]) for item in TABS]
TAB_LABELS = dict(TAB_LIST)
DEFAULT_TAB = TAB_LIST[0][0]
DETAIL_LIMIT = int(CONFIG.get("detail_row_limit", 1000))

PORTFOLIO_COLUMNS = [
    "check_date", "check_month", "line_state", "category", "borrower_category",
    "incorporation_type", "status", "city", "state", "zone", "loan_product",
    "product_tag", "lender_name", "anchor_name", "par_0_plus", "par_30_plus",
    "par_60_plus", "par_90_plus", "par_150_plus", "par_180_plus", "total_aum",
    "write_off_flag", "current_date_flag", "limit_bucket",
    "org_type", "credit_line_ct", "par_0_plus_ct", "par_30_plus_ct",
    "par_60_plus_ct", "par_90_plus_ct", "par_150_plus_ct", "par_180_plus_ct",
    "roi_bucket", "uw_spoc",
]
NS_COLUMNS = [
    "actual_due_date_ist", "actual_due_month", "drawdown_id", "installment_id",
    "credit_line_id", "borrower_id", "borrower_name", "Borrower_Category", "anchor",
    "lender", "state", "tenant", "type", "uw_spoc", "zone", "flag_ns_ever",
    "flag_ns_residual", "flag_em_ever", "flag_em_residual",
]
POTENTIAL_COLUMNS = [
    "credit_line_id", "actual_due_date_ist", "borrower_id", "borrower_name", "uw_spoc",
    "tenant", "anchor", "lender", "state", "zone", "max_dpd", "total_aum_ns",
    "total_aum_em", "line_limit", "flag_pot_ns", "flag_pot_em",
]
ENHANCEMENT_COLUMNS = [
    "check_date", "credit_line_id", "org_id", "borrower_name", "anchor", "lender",
    "product_type", "line_limit", "total_aum", "current_utilization", "m_1_utilization",
    "m_2_utilization", "m_3_utilization", "current_max_dpd", "L_90_max_dpd",
    "L_180_max_dpd", "open_market_limit", "anchor_limit",
]

DATA: dict[str, pd.DataFrame] = {name: pd.DataFrame() for name in TABLES}
LOAD_ERRORS: dict[str, str] = {}
LOADED_AT = "Source timestamp unavailable"


def _add_power_bi_model_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Recreate PBIT calculated columns without querying them as source fields."""
    if frame.empty:
        return frame
    result = frame.copy()
    calculated_aliases = {
        "Total_aum_in_cr": "total_aum",
        "par_0_plus_cr": "par_0_plus",
        "par_30_plus_cr": "par_30_plus",
        "par_60_plus_cr": "par_60_plus",
        "par_90_plus_cr": "par_90_plus",
    }
    for calculated, physical in calculated_aliases.items():
        if physical in result.columns:
            result[calculated] = result[physical]
    if "anchor_name" in result.columns:
        result["anchor_tag"] = np.where(
            result["anchor_name"].astype(str).eq("Non-Anchor"),
            "Non Anchor",
            "Anchor",
        )
    return result


def _load_data() -> bool:
    """Load source-defined columns once; all tab changes aggregate the local snapshot."""
    global LOADED_AT
    queries = {
        "portfolio": (
            f"SELECT {', '.join(PORTFOLIO_COLUMNS)}, "
            "final_product_tag AS `Product Tag`, "
            "oldest_bureau_score_bucket AS onboarding_bureau_score_bucket "
            f"FROM {TABLES['portfolio']}"
        ),
        "ns_em": f"SELECT {', '.join(NS_COLUMNS)} FROM {TABLES['ns_em']}",
        "potential": f"SELECT {', '.join(POTENTIAL_COLUMNS)} FROM {TABLES['potential']}",
        "enhancement": f"SELECT {', '.join(ENHANCEMENT_COLUMNS)} FROM {TABLES['enhancement']}",
    }
    all_ok = True
    for name, query in queries.items():
        try:
            loaded = run_query(query, context=f"portfolio:{name}", raise_on_error=True)
            DATA[name] = _add_power_bi_model_columns(loaded) if name == "portfolio" else loaded
            LOAD_ERRORS.pop(name, None)
        except Exception as exc:
            all_ok = False
            LOAD_ERRORS[name] = str(exc)
            print(f"[portfolio] {name} load failed: {exc}", file=sys.stderr)
    LOADED_AT = format_timestamp(pd.Timestamp.now(tz="Asia/Kolkata"))
    return all_ok


def refresh_data():
    """Public whole-page refresh hook used by the app scheduler."""
    return _load_data()


_load_data()


def _month_label(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%b-%y") if pd.notna(parsed) else str(value)


def _monthly_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "check_month" in result:
        result["_month"] = result["check_month"].map(_month_label)
    return result


def _options(frame: pd.DataFrame, column: str) -> list[str]:
    return unique_values(frame, column, stringify=True)


def _filter_definitions(tab_id: str):
    if tab_id == "ns-em":
        return [(c, l) for c, l in [
            ("state", "State"), ("uw_spoc", "UW SPOC"),
            ("actual_due_month", "Due Month"), ("tenant", "Tenant"),
            ("anchor", "Anchor"), ("Borrower_Category", "Borrower Category"),
        ]]
    if tab_id in {"possible-ns", "cb-enhancement"}:
        return []
    return [tuple(item) for item in CONFIG["common_filters"]]


def _source_frame(tab_id: str) -> pd.DataFrame:
    return DATA["ns_em"] if tab_id == "ns-em" else DATA["portfolio"]


def _filters(tab_id: str):
    frame = _source_frame(tab_id)
    return [
        filter_ui(label, f"pm-{tab_id}-{column}", _options(frame, column), multi=True, variant="accent")
        for column, label in _filter_definitions(tab_id) if column in frame.columns
    ]


def _apply(frame: pd.DataFrame, definitions, values) -> pd.DataFrame:
    selected = {column: value for (column, _), value in zip(definitions, values) if value}
    return filter_frame(frame, selected, stringify=True)


def _with_current_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    if "current_date_flag" not in frame.columns:
        return frame
    numeric = pd.to_numeric(frame["current_date_flag"], errors="coerce")
    return frame.loc[numeric.eq(1)]


def _overall_summary(frame: pd.DataFrame, dimension: str, *, lines: bool = False) -> pd.DataFrame:
    if frame.empty or dimension not in frame.columns:
        return pd.DataFrame()
    if lines:
        numerators = ["par_0_plus_ct", "par_30_plus_ct", "par_60_plus_ct", "par_90_plus_ct"]
        denominator = "credit_line_ct"
        labels = ["0", "30", "60", "90"]
        value_suffix = " Lines"
    else:
        numerators = ["par_0_plus_cr", "par_30_plus_cr", "par_60_plus_cr", "par_90_plus_cr"]
        denominator = "Total_aum_in_cr"
        labels = ["0", "30", "60", "90"]
        value_suffix = " PAR (Cr)"
    work = frame.copy()
    numeric = [denominator, *numerators]
    for column in numeric:
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0)
    grouped = work.groupby(dimension, dropna=False, sort=False)[numeric].sum().reset_index()
    rename = {denominator: "Total Lines" if lines else "Total AUM (Cr)"}
    rename.update({column: f"{label}+{value_suffix}" for column, label in zip(numerators, labels)})
    grouped = grouped.rename(columns=rename)
    total_name = rename[denominator]
    for column, label in zip(numerators, labels):
        value_name = rename[column]
        grouped[f"{label}+ %"] = np.where(grouped[total_name].ne(0), grouped[value_name] / grouped[total_name] * 100, 0)
    total = {dimension: "Total"}
    for column in [total_name, *[rename[c] for c in numerators]]:
        total[column] = grouped[column].sum()
    for column, label in zip(numerators, labels):
        value_name = rename[column]
        total[f"{label}+ %"] = total[value_name] / total[total_name] * 100 if total[total_name] else 0
    result = pd.concat([grouped, pd.DataFrame([total])], ignore_index=True)
    ordered = [dimension, total_name]
    for column, label in zip(numerators, labels):
        ordered.extend([rename[column], f"{label}+ %"])
    return result[ordered].round(2)


def _monthly_pivot(frame: pd.DataFrame, dimension: str, value: str, denominator: str | None) -> pd.DataFrame:
    work = _monthly_frame(frame)
    return make_financial_pivot(
        work, dimension, "_month", value, fmt="{:.2f}",
        pct=denominator is not None, pct_denom=denominator,
    )


def _table(
    frame: pd.DataFrame,
    title: str,
    component_id: str,
    *,
    height: int = 430,
    downloadable: bool = True,
):
    return visual_card(
        table_ui(
            frame, component_id=component_id, max_height=height,
            downloadable=downloadable,
        ),
        title=title,
    )


@with_visual_scope("portfolio", "master-aum")
def _master_visuals(frame: pd.DataFrame):
    work = _monthly_frame(frame)
    values = ["total_aum", "par_0_plus", "par_30_plus", "par_60_plus", "par_90_plus", "par_150_plus", "par_180_plus"]
    counts = ["credit_line_ct", "par_0_plus_ct", "par_30_plus_ct", "par_60_plus_ct", "par_90_plus_ct", "par_150_plus_ct", "par_180_plus_ct"]
    def metric_matrix(columns, labels):
        rows = []
        months = sorted(work["_month"].dropna().unique(), key=lambda x: pd.to_datetime(x, format="%b-%y", errors="coerce"), reverse=True)
        for column, label in zip(columns, labels):
            grouped = pd.to_numeric(work[column], errors="coerce").groupby(work["_month"]).sum()
            rows.append({"Metric": label, **{month: round(grouped.get(month, 0), 2) for month in months}})
        return pd.DataFrame(rows)
    # Visual 6.1.1 | table | i4dzcz | Monthly delinquency book value
    value_table = _table(metric_matrix(values, ["Total AUM", "0+ PAR", "30+ PAR", "60+ PAR", "90+ PAR", "150+ PAR", "180+ PAR"]), "Delinquency book value by month", "pm-master-values")
    # Visual 6.1.2 | table | i4dzcz | Monthly delinquency line count
    count_table = _table(metric_matrix(counts, ["Total Lines", "0+ Lines", "30+ Lines", "60+ Lines", "90+ Lines", "150+ Lines", "180+ Lines"]), "Delinquency line count by month", "pm-master-counts")
    return [value_table, count_table]


# Visual 6.2.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.2.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.2.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.2.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.2.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.2.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.2.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.3.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.4.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.5.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.6.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.7.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.8.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.9.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.10.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.11.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.12.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.7 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.8 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.13.9 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.14.1 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.14.2 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.14.3 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.14.4 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.14.5 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.14.6 | table | i4dzcz | Portfolio Monitoring configured visual
# Visual 6.14.7 | table | i4dzcz | Portfolio Monitoring configured visual
def _overall_visuals(tab_id: str, frame: pd.DataFrame, *, lines: bool = False):
    @with_visual_scope("portfolio", tab_id)
    def render():
        result = []
        for index, (dimension, label) in enumerate(CONFIG["overall_dimensions"], start=1):
            result.append(_table(_overall_summary(frame, dimension, lines=lines), f"{'Lines' if lines else 'Book Value'} | {label} wise", f"pm-{tab_id}-{index}"))
        return result
    return render()


def _dimension_visuals(tab_id: str, frame: pd.DataFrame):
    dimension, label = CONFIG["dimension_pages"][tab_id]
    @with_visual_scope("portfolio", tab_id)
    def render():
        result = []
        for index, (value, metric_label, denominator) in enumerate(CONFIG["monthly_metrics"], start=1):
            # Ticket Size's 60+ value visual uses lender in the supplied PBIT.
            row_dimension = "lender_name" if tab_id == "ticket-size" and index == 6 else dimension
            result.append(_table(_monthly_pivot(frame, row_dimension, value, denominator), f"{label} | {metric_label} by month", f"pm-{tab_id}-{index}"))
        return result
    return render()


@with_visual_scope("portfolio", "ns-em")
def _ns_em_visuals(frame: pd.DataFrame):
    numeric = ["flag_ns_ever", "flag_ns_residual", "flag_em_ever", "flag_em_residual"]
    work = frame.copy()
    for column in numeric:
        work[column] = pd.to_numeric(work[column], errors="coerce").fillna(0)
    if work.empty:
        summary = pd.DataFrame()
    else:
        summary = work.groupby("actual_due_month", dropna=False, sort=False).agg(
            **{"Credit Lines": ("credit_line_id", "count"), "NS Ever": ("flag_ns_ever", "sum"),
               "NS Residual": ("flag_ns_residual", "sum"), "EM Ever": ("flag_em_ever", "sum"),
               "EM Residual": ("flag_em_residual", "sum")}
        ).reset_index()
    # Visual 6.15.1 | table | f7cbqv | NS and EM summary by due month
    first = _table(summary, "Non Starter & Early Mortality summary", "pm-ns-summary")
    # Visual 6.15.2 | table | f7cbqv | NS and EM case detail
    second = _table(
        work.reindex(columns=NS_COLUMNS).head(DETAIL_LIMIT),
        "Case detail", "pm-ns-detail", height=560, downloadable=False,
    )
    return [first, second]


@with_visual_scope("portfolio", "possible-ns")
def _possible_ns_visuals():
    frame = DATA["potential"]
    flag = pd.to_numeric(frame.get("flag_pot_ns", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    visible_columns = [c for c in POTENTIAL_COLUMNS if c not in {"flag_pot_ns", "flag_pot_em", "total_aum_em"}]
    result = frame.loc[flag.eq(1)].reindex(columns=visible_columns).head(DETAIL_LIMIT)
    # Visual 6.16.1 | table | g4nqsv | Possible non-starter cases
    return [_table(
        result, "Possible Non Starter Cases", "pm-possible-ns",
        height=620, downloadable=False,
    )]


@with_visual_scope("portfolio", "cb-enhancement")
def _cb_visuals():
    potential = DATA["potential"]
    flag = pd.to_numeric(potential.get("flag_pot_em", pd.Series(index=potential.index, dtype=float)), errors="coerce")
    early_columns = [c for c in POTENTIAL_COLUMNS if c not in {"flag_pot_ns", "flag_pot_em", "total_aum_ns", "zone"}]
    # Visual 6.17.1 | table | g4nqsv | Possible early mortality cases
    first = _table(
        potential.loc[flag.eq(1)].reindex(columns=early_columns).head(DETAIL_LIMIT),
        "Possible Early Mortality Cases", "pm-possible-em",
        height=520, downloadable=False,
    )
    # Visual 6.17.2 | table | wtyaum | Possible CB+ enhancement cases
    second = _table(
        DATA["enhancement"].reindex(columns=ENHANCEMENT_COLUMNS).head(DETAIL_LIMIT),
        "Possible CB+ Enhancement Cases", "pm-enhancement",
        height=620, downloadable=False,
    )
    return [first, second]


def _render_visuals(tab_id: str, frame: pd.DataFrame):
    if tab_id == "master-aum":
        return _master_visuals(frame)
    if tab_id == "overall-aum":
        return _overall_visuals(tab_id, _with_current_snapshot(frame))
    if tab_id == "overall-lines":
        return _overall_visuals(tab_id, _with_current_snapshot(frame), lines=True)
    if tab_id in CONFIG["dimension_pages"]:
        return _dimension_visuals(tab_id, frame)
    if tab_id == "ns-em":
        return _ns_em_visuals(frame)
    if tab_id == "possible-ns":
        return _possible_ns_visuals()
    return _cb_visuals()


def _page(tab_id: str):
    definitions = _filter_definitions(tab_id)
    frame = _source_frame(tab_id)
    error_key = "ns_em" if tab_id == "ns-em" else "portfolio"
    errors = LOAD_ERRORS.get(error_key)
    controls = _filters(tab_id)
    if controls:
        controls.append(clear_filters_button(f"pm-{tab_id}-clear"))
    status = f"{len(frame):,} source rows loaded"
    if tab_id in {"possible-ns", "cb-enhancement"}:
        status = f"Detail tables show up to {DETAIL_LIMIT:,} rows; full filtered CSV export is available"
    children = [
        header_ui(TAB_LABELS[tab_id], subtitle=CONFIG["title"], updated_text=LOADED_AT),
    ]
    if controls:
        children.append(visual_card(html.Div(controls, className="ui-filter-row"), title="Filters"))
    if tab_id == "ns-em":
        children.append(full_export_controls("pm-ns-em-export-all", "pm-ns-em-download-all"))
    elif tab_id == "possible-ns":
        children.append(full_export_controls("pm-possible-ns-export-all", "pm-possible-ns-download-all"))
    elif tab_id == "cb-enhancement":
        children.extend([
            full_export_controls(
                "pm-possible-em-export-all", "pm-possible-em-download-all",
                label="Export all filtered early-mortality rows",
            ),
            full_export_controls(
                "pm-enhancement-export-all", "pm-enhancement-download-all",
                label="Export all enhancement rows",
            ),
        ])
    visual_content = (
        html.Div(f"Data load error: {errors}", className="ui-state ui-state--error")
        if errors and frame.empty else _render_visuals(tab_id, frame)
    )
    children.append(html.Div(visual_content, id=f"pm-{tab_id}-content", className="ui-vertical-visuals"))
    children.append(html.Div(status, id=f"pm-{tab_id}-status", className="ui-page-subtitle"))
    return html.Div(children, className="ui-page-body")


def layout():
    return html.Div([
        dcc.Store(id="pm-active-tab", data=DEFAULT_TAB),
        html.Div(tab_bar(TAB_LIST, id_prefix="pm-tab-", active=DEFAULT_TAB), id="pm-tabs"),
        html.Div(id="pm-page-content"),
    ], style={"background": "#f0f0f3", "minHeight": "100vh"})


@callback(
    Output("pm-active-tab", "data"),
    [Input(f"pm-tab-{tab_id}", "n_clicks") for tab_id, _ in TAB_LIST] + [Input("pm-tab-mobile", "value")],
    prevent_initial_call=True,
)
def select_tab(*values):
    if ctx.triggered_id == "pm-tab-mobile":
        selected = values[-1] or no_update
    else:
        selected = str(ctx.triggered_id).removeprefix("pm-tab-") if ctx.triggered_id else no_update
    if selected is not no_update:
        track_tab_click("portfolio", selected)
    return selected


@callback([Output("pm-tabs", "children"), Output("pm-page-content", "children")], Input("pm-active-tab", "data"))
def render_tab(active):
    selected = active if active in TAB_LABELS else DEFAULT_TAB
    return tab_bar(TAB_LIST, id_prefix="pm-tab-", active=selected), _page(selected)


def _register_filter_callbacks() -> None:
    for tab_id, _label in TAB_LIST:
        definitions = _filter_definitions(tab_id)
        filter_ids = [f"pm-{tab_id}-{column}" for column, _ in definitions]
        if not filter_ids:
            continue
        register_filter_reset(f"pm-{tab_id}-clear", filter_ids)

        def register(current_tab=tab_id, current_definitions=definitions, current_ids=filter_ids):
            @callback(
                [Output(f"pm-{current_tab}-content", "children"), Output(f"pm-{current_tab}-status", "children")],
                [Input(component_id, "value") for component_id in current_ids],
                prevent_initial_call=True,
            )
            def update_page(*values):
                source = _source_frame(current_tab)
                filtered = _apply(source, current_definitions, values)
                return _render_visuals(current_tab, filtered), f"{len(filtered):,} filtered rows"
        register()


_register_filter_callbacks()


NS_EM_FILTER_DEFINITIONS = _filter_definitions("ns-em")
NS_EM_FILTER_IDS = [
    f"pm-ns-em-{column}" for column, _label in NS_EM_FILTER_DEFINITIONS
]


@callback(
    Output("pm-ns-em-download-all", "data"),
    Input("pm-ns-em-export-all", "n_clicks"),
    [State(component_id, "value") for component_id in NS_EM_FILTER_IDS],
    prevent_initial_call=True,
)
def export_all_ns_em(_n_clicks, *values):
    filtered = _apply(DATA["ns_em"], NS_EM_FILTER_DEFINITIONS, values)
    export = filtered.reindex(columns=NS_COLUMNS)
    if export.empty:
        return no_update
    return dcc.send_data_frame(
        export.to_csv,
        "portfolio_ns_em_filtered.csv",
        index=False,
    )


@callback(
    Output("pm-possible-ns-download-all", "data"),
    Input("pm-possible-ns-export-all", "n_clicks"),
    prevent_initial_call=True,
)
def export_all_possible_ns(_n_clicks):
    frame = DATA["potential"]
    flag = pd.to_numeric(
        frame.get("flag_pot_ns", pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    )
    columns = [
        column for column in POTENTIAL_COLUMNS
        if column not in {"flag_pot_ns", "flag_pot_em", "total_aum_em"}
    ]
    export = frame.loc[flag.eq(1)].reindex(columns=columns)
    if export.empty:
        return no_update
    return dcc.send_data_frame(
        export.to_csv,
        "portfolio_possible_non_starters.csv",
        index=False,
    )


@callback(
    Output("pm-possible-em-download-all", "data"),
    Input("pm-possible-em-export-all", "n_clicks"),
    prevent_initial_call=True,
)
def export_all_possible_em(_n_clicks):
    frame = DATA["potential"]
    flag = pd.to_numeric(
        frame.get("flag_pot_em", pd.Series(index=frame.index, dtype=float)),
        errors="coerce",
    )
    columns = [
        column for column in POTENTIAL_COLUMNS
        if column not in {"flag_pot_ns", "flag_pot_em", "total_aum_ns", "zone"}
    ]
    export = frame.loc[flag.eq(1)].reindex(columns=columns)
    if export.empty:
        return no_update
    return dcc.send_data_frame(
        export.to_csv,
        "portfolio_possible_early_mortality.csv",
        index=False,
    )


@callback(
    Output("pm-enhancement-download-all", "data"),
    Input("pm-enhancement-export-all", "n_clicks"),
    prevent_initial_call=True,
)
def export_all_enhancement(_n_clicks):
    export = DATA["enhancement"].reindex(columns=ENHANCEMENT_COLUMNS)
    if export.empty:
        return no_update
    return dcc.send_data_frame(
        export.to_csv,
        "portfolio_cb_enhancement.csv",
        index=False,
    )
