"""AUM Dashboard — Databricks App (all 16 Power BI pages)."""
import os, sys, threading, warnings
warnings.filterwarnings("ignore")
import pandas as pd
import numpy as np
from dash import Dash, html, dcc, callback, Input, Output, State, no_update
import plotly.graph_objects as go
import plotly.express as px
from ui import (
    NAVIGATION, theme_value, filter_ui, header_ui, section_title as ui_section_title,
    empty_state as ui_empty_state, matrix_table, table_ui, link_tab_bar,
    line_chart as ui_line_chart, multi_line_chart as ui_multi_line_chart,
    clear_filters_button, full_export_controls, register_filter_reset, visual_scope,
)
from shared import (
    filter_frame as filt,
    format_timestamp,
    make_financial_pivot as make_pivot,
    normalise_filters as build_filters,
    run_query,
    track_tab_click,
    to_numeric as to_num,
    unique_values as uvals,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
WAREHOUSE_ID = os.getenv("DATABRICKS_WAREHOUSE_ID", "e6b3b3d8399e5edb")
SCHEMA = "hive_metastore.probes"

# ---------------------------------------------------------------------------
# Load all datasets
# ---------------------------------------------------------------------------
print("[STARTUP] Loading data...", file=sys.stderr)

DF = {}
_AUM_QUERIES = {}


def _load_dataset(name, query):
    """Remember each query so an AUM page can recover from a transient startup failure."""
    _AUM_QUERIES[name] = query
    return run_query(query, context=f"aum:{name}")


def _ensure_dataset(name):
    """Retry an unavailable dataset when its page is opened."""
    frame = DF.get(name, pd.DataFrame())
    query = _AUM_QUERIES.get(name)
    if frame.empty and query:
        frame = _load_dataset(name, query)
        DF[name] = frame
    return frame

try:
    DF["book"] = _load_dataset("book", f"""
        SELECT t.*,
          CASE
            WHEN _col = 'Vendor_Aggregator' THEN '9.Vendor_Aggregator'
            WHEN _col = 'Credit_BUY' OR _col = 'Credit_Buy' THEN '7.Credit_buy'
            WHEN _col = 'CnC_VF' THEN '5.CnC_VF'
            WHEN _col = 'QC_Family' THEN '3.QC_Family'
            WHEN _col = 'EMI' THEN '4.EMI'
            WHEN _col = 'Pratishtha_LT' THEN '1.Pratishtha_LT'
            WHEN _col = 'Pratishtha_ST' THEN '2.Pratishtha_ST'
            WHEN _col IN ('CnC_PF','OD_CnC','OD_CNC','Payroll_Financing') THEN '8.Intercompany'
            WHEN _col = '6.OD_TL' THEN '6.OD_TL'
            WHEN _col = '1.Pratishtha_LT' THEN '1.Pratishtha_LT'
            ELSE _col
          END AS Product,
          anchor AS Anchor, anchor AS Anchors, anchor_type AS Anchor_type,
          AUM/1e7 AS total_aum, Npa/1e7 AS Npa_1,
          `30_plus_par`/1e7 AS `30_plus_par_1`, `60_plus_par`/1e7 AS `60_plus_par_1`,
          `0_plus_par`/1e7 AS `0_plus_par_1`, write_off/1e7 AS `write-off_1`,
          disb_amt_Month/1e7 AS Disbursal_amt
        FROM (
          SELECT *,
            CASE
              WHEN org_type = 'Pratishtha_LT' THEN channel_type
              WHEN org_type = 'PAYMENT_REVERSAL' THEN 'Credit_Buy'
              WHEN org_type IN ('INVOICE_FINANCING','CREDIT_BUY_PLUS') THEN '1.Pratishtha_LT'
              WHEN channel_type = 'Vendor_Aggregator' THEN 'Vendor_Aggregator'
              WHEN org_type IN ('OD_BAU','OD','TL','TERM_LOAN') THEN '6.OD_TL'
              ELSE org_type
            END AS _col
          FROM {SCHEMA}.book_size_updates_dzezet
        ) t""")
    DF["daily_aum"] = _load_dataset("daily_aum", f"""
        SELECT t.*,
          total_aum/1e7 AS Total_AUM_1,
          CASE
            WHEN _col = 'Vendor_Aggregator' THEN '9.Vendor_Aggregator'
            WHEN _col IN ('Credit_BUY','Credit_Buy','creditbuy','Creditt_buy') THEN '7.Credit_buy'
            WHEN _col = 'CnC_VF' THEN '5.CnC_VF'
            WHEN _col = 'QC_Family' THEN '3.QC_Family'
            WHEN _col = 'EMI' THEN '4.EMI'
            WHEN _col = 'Pratishtha_LT' THEN '1.Pratishtha_LT'
            WHEN _col = 'Pratishtha_ST' THEN '2.Pratishtha_ST'
            WHEN _col IN ('CnC_PF','OD_CnC','OD_CNC','Payroll_Financing') THEN '8.Intercompany'
            WHEN _col = 'Seller' THEN '6.Seller'
            WHEN _col = '6.OD_TL' THEN '6.OD_TL'
            WHEN _col = '1.Pratishtha_LT' THEN '1.Pratishtha_LT'
            ELSE _col
          END AS Product
        FROM (
          SELECT *,
            CASE
              WHEN org_type = 'Pratishtha_LT' THEN channel_type
              WHEN org_type = 'PAYMENT_REVERSAL' THEN 'Credit_Buy'
              WHEN org_type IN ('INVOICE_FINANCING','CREDIT_BUY_PLUS') THEN '1.Pratishtha_LT'
              WHEN channel_type = 'Vendor_Aggregator' THEN 'Vendor_Aggregator'
              WHEN org_type IN ('OD_BAU','OD','TL','TERM_LOAN') THEN '6.OD_TL'
              ELSE org_type
            END AS _col
          FROM {SCHEMA}.dailyaum_fyy6q3
        ) t""")
    DF["par"] = _load_dataset("par", f"""
        SELECT *, total_aum/1e7 AS AUM, par_0_plus/1e7 AS par_0_plus_cr,
               par_30_plus/1e7 AS par_30_plus_cr, par_60_plus/1e7 AS par_60_plus_cr,
               par_90_plus/1e7 AS par_90_plus_cr, par_15_plus/1e7 AS par_15_plus_cr,
               check_date AS actual_date, anchor_tag AS Product
        FROM {SCHEMA}.aum_0_30_plus_gwziy4""")
    DF["interco"] = _load_dataset("interco", f"SELECT * FROM {SCHEMA}.intercompany_booksize_f73jfw")
    DF["l30"] = pd.DataFrame()
    DF["lt_coll"] = _load_dataset("lt_coll", f"SELECT * FROM {SCHEMA}.lt_collection_check_month_fbtkmw")
    DF["dupe"] = _load_dataset("dupe", f"""
        SELECT t2.*,
          CASE
            WHEN _col2 = 'Vendor_Aggregator' THEN '9.Vendor_Aggregator'
            WHEN _col2 IN ('Credit_BUY','Credit_Buy') THEN '7.Credit_buy'
            WHEN _col2 = 'CnC_VF' THEN '5.CnC_VF'
            WHEN _col2 = 'QC_Family' THEN '3.QC_Family'
            WHEN _col2 = 'EMI' THEN '4.EMI'
            WHEN _col2 = 'Pratishtha_LT' THEN '1.Pratishtha_LT'
            WHEN _col2 = 'Pratishtha_ST' THEN '2.Pratishtha_ST'
            WHEN _col2 IN ('CnC_PF','OD_CnC','OD_CNC','Payroll_Financing') THEN '8.Intercompany'
            WHEN _col2 = '6.OD_TL' THEN '6.OD_TL'
            WHEN _col2 = '1.Pratishtha_LT' THEN '1.Pratishtha_LT'
            ELSE _col2
          END AS Product_x,
          AUM/1e7 AS total_aum_x, `90_to_270_par`/1e7 AS Npa_90_270
        FROM (
          SELECT *,
            CASE
              WHEN org_type = 'Pratishtha_LT' THEN channel_type
              WHEN org_type = 'PAYMENT_REVERSAL' THEN 'Credit_Buy'
              WHEN org_type IN ('INVOICE_FINANCING','CREDIT_BUY_PLUS') THEN '1.Pratishtha_LT'
              WHEN channel_type = 'Vendor_Aggregator' THEN 'Vendor_Aggregator'
              WHEN org_type IN ('OD_BAU','OD','TL','TERM_LOAN') THEN '6.OD_TL'
              ELSE org_type
            END AS _col2
          FROM {SCHEMA}.book_size_updates_dupe_otxlat
        ) t2""")
    DF["dpd"] = _load_dataset("dpd", f"SELECT * FROM {SCHEMA}.p_st_aum_dv2jpb")
    DF["exact_dpd"] = _load_dataset(
        "exact_dpd", f"SELECT * FROM {SCHEMA}.prat_exact_dpd_di6x4p"
    )
    # Post-load: ensure numeric types
    for key in DF:
        df = DF[key]
        if df.empty: continue
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col], errors='ignore')
            except: pass
    print(f"[STARTUP] Data loaded. Tables: {[(k,len(v)) for k,v in DF.items()]}", file=sys.stderr)
except Exception as e:
    print(f"[STARTUP ERROR] {e}", file=sys.stderr)


def _latest_source_update() -> str:
    """Best available source timestamp; never label the current clock as freshness."""
    candidates = []
    for frame in DF.values():
        if frame is None or frame.empty:
            continue
        for column in ("refresh_time", "updated_at", "latest_updated_at"):
            if column in frame.columns:
                values = pd.to_datetime(frame[column], errors="coerce").dropna()
                if not values.empty:
                    candidates.append(values.max())
    return format_timestamp(max(candidates)) if candidates else "Source timestamp unavailable"


DATA_UPDATED_TEXT = _latest_source_update()
_REFRESH_LOCK = threading.Lock()


def refresh_data():
    """Atomically replace every AUM dataset after a complete successful reload."""
    global DF, DATA_UPDATED_TEXT
    with _REFRESH_LOCK:
        refreshed = {}
        for name, query in _AUM_QUERIES.items():
            frame = run_query(query, context=f"aum:{name}", raise_on_error=True)
            for column in frame.columns:
                try:
                    frame[column] = pd.to_numeric(frame[column], errors="ignore")
                except Exception:
                    pass
            refreshed[name] = frame
        # l30 is intentionally local/empty and has no source query.
        if "l30" in DF:
            refreshed["l30"] = DF["l30"]
        DF = refreshed
        DATA_UPDATED_TEXT = _latest_source_update()
        return True

# ---------------------------------------------------------------------------
# Style Tokens (matching PBI palette)
# ---------------------------------------------------------------------------
RED = theme_value("colors.primary", "#DE1414")
BG = theme_value("colors.surface", "#FFFFFF")
TEXT = theme_value("colors.text", "#252423")
TEXT_LIGHT = theme_value("colors.muted", "#605E5C")
GRID_HEADER = "#F3F2F1"
YELLOW_HEADER = "#FFD966"
BLUE = "#118DFF"
DARK_BLUE = "#12239E"
ORANGE = "#E66C37"

def pivot_table_component(pv, id_prefix, highlight_col=None):
    return matrix_table(pv, id_prefix, highlight_first_column=bool(highlight_col))

def make_dropdown(label, id_, options, multi=True):
    return filter_ui(label, id_, options, multi=multi, variant="accent")

def section_title(text):
    return ui_section_title(text)

def header_bar(title, subtitle="All values post write-off"):
    return header_ui(title, subtitle=subtitle, updated_text=DATA_UPDATED_TEXT)

def empty_state(msg="No data available for selected filters"):
    return ui_empty_state(msg)

def safe_callback(fn):
    """Decorator: catch all errors in callbacks so the app never returns 500/502."""
    import functools, traceback as _tb
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            if fn.__name__.startswith("update_p"):
                page_number = int(fn.__name__.removeprefix("update_p"))
                tab_id = PAGE_LIST[page_number - 1][0]
                with visual_scope("aum", tab_id):
                    return fn(*args, **kwargs)
            return fn(*args, **kwargs)
        except Exception as e:
            _tb.print_exc(file=sys.stderr)
            return html.Div([
                html.P(f"Error rendering this section: {e}",
                       style={"color": RED, "padding": "20px", "fontSize": "13px"}),
            ])
    return wrapper

def line_chart(df, x, y, title, color=BLUE, pct=False):
    return ui_line_chart(df, x, y, title, color=color, pct=pct)

def multi_line_chart(df, x, y_cols, title, labels=None, colors=None):
    return ui_multi_line_chart(df, x, y_cols, title, labels=labels, colors=colors)

# Prepare month labels
def add_month_label(df, date_col="check_month"):
    if date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df["_mlabel"] = df[date_col].dt.strftime("%b-%y")
        df["_msort"] = df[date_col]
    return df

# ---------------------------------------------------------------------------
# Page Definitions
# ---------------------------------------------------------------------------
PAGE_LIST = [
    (page["id"], page["label"])
    for page in sorted(NAVIGATION["subpages"]["aum"], key=lambda item: item.get("order", 0))
]

_AUM_FILTER_GROUPS = {
    "p1": ["p1-lender", "p1-product", "p1-channel", "p1-bucket", "p1-atype"],
    "p2": ["p2-lender", "p2-product", "p2-channel"],
    "p3": ["p3-lender", "p3-product", "p3-channel", "p3-bucket"],
    "p4": ["p4-lender", "p4-product", "p4-channel", "p4-atag"],
    "p5": ["p5-anchor", "p5-atype", "p5-product", "p5-org", "p5-lender"],
    "p6": ["p6-ancname", "p6-atype", "p6-product", "p6-org", "p6-lender"],
    "p7": ["p7-lender", "p7-anchor", "p7-bucket", "p7-atype", "p7-bd"],
    "p8": ["p8-lender", "p8-anchor", "p8-bucket", "p8-atype"],
    "p9": ["p9-lender", "p9-anchor", "p9-bucket", "p9-atype"],
    "p10": ["p10-lender", "p10-anchor", "p10-bucket", "p10-atype", "p10-bd"],
    "p11": ["p11-lender", "p11-anchor", "p11-bucket", "p11-atype", "p11-cat"],
    "p12": ["p12-lender", "p12-product", "p12-atype", "p12-bucket"],
    "p13": ["p13-dpd", "p13-lender", "p13-org", "p13-flag"],
    "p14": ["p14-lender", "p14-product", "p14-anchor", "p14-bucket"],
    "p15": [
        "p15-orgid", "p15-orgname", "p15-category", "p15-maxdpd1",
        "p15-zone", "p15-loantype", "p15-reportmonth", "p15-maxdpd",
        "p15-state", "p15-bim", "p15-spoc", "p15-city",
    ],
    "p16": ["p16-lender", "p16-product", "p16-anchor", "p16-bucket", "p16-atype", "p16-rsm"],
}

for _page_prefix, _filter_ids in _AUM_FILTER_GROUPS.items():
    register_filter_reset(f"{_page_prefix}-clear", _filter_ids)

# ---------------------------------------------------------------------------
# Dash App
# ---------------------------------------------------------------------------

def build_nav(active_pid="uc-aum-npa"):
    return link_tab_bar(PAGE_LIST, active=active_pid, mobile_id="aum-nav-mobile")



def layout():
    return html.Div([
        dcc.Location(id="url", refresh=False),
        html.Div(id="nav-bar", style={"background": BG, "borderBottom": "1px solid #E1DFDD",
                                        "position": "sticky", "top": 0, "zIndex": 100}),
        html.Div(id="page-content", style={"padding": "16px 20px", "maxWidth": "1400px", "margin": "0 auto"}),
], style={"background": "#FAFAFA", "minHeight": "100vh"})

@callback(Output("nav-bar", "children"), Input("url", "pathname"))
def update_nav(pathname):
    p = (pathname or "/").strip("/") or "uc-aum-npa"
    track_tab_click("aum", p)
    return build_nav(p)


@callback(Output("url", "pathname"), Input("aum-nav-mobile", "value"), prevent_initial_call=True)
def update_mobile_nav(page_id):
    return f"/{page_id}" if page_id else no_update

# ===================== PAGE 1: uC (AUM & NPA) =====================
def page_uc_aum_npa():
    df = DF.get("book", pd.DataFrame())
    return html.Div([
        header_bar("uC Lender: HCPL + 3PL"),
        html.Div([
            make_dropdown("Lender", "p1-lender", uvals(df, "lender")),
            make_dropdown("Product", "p1-product", uvals(df, "Product")),
            make_dropdown("Channel Type", "p1-channel", uvals(df, "channel_type")),
            make_dropdown("Bucket Size", "p1-bucket", uvals(df, "bucket_size")),
            make_dropdown("Anchor Type", "p1-atype", uvals(df, "Anchor_type")),
            clear_filters_button("p1-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p1-content"),
    ])

@callback(Output("p1-content", "children"),
          [Input("p1-lender","value"), Input("p1-product","value"),
           Input("p1-channel","value"), Input("p1-bucket","value"), Input("p1-atype","value")])
@safe_callback
def update_p1(lender, product, channel, bucket, atype):
    df = DF.get("book", pd.DataFrame())
    if df.empty: return empty_state()
    f = build_filters({"lender":lender,"Product":product,"channel_type":channel,"bucket_size":bucket,"Anchor_type":atype})
    d = filt(df, f)
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["total_aum","Npa_1","30_plus_par_1","60_plus_par_1","write-off_1","0_plus_par_1"])
    pv_aum = make_pivot(d, "Product", "_mlabel", "total_aum", divide=1, fmt="{:.2f}")
    pv_npa_pct = make_pivot(d, "Product", "_mlabel", "Npa_1", pct=True, pct_denom="total_aum", fmt="{:.2f}%")
    pv_npa = make_pivot(d, "Product", "_mlabel", "Npa_1", divide=1, fmt="{:.2f}")
    pv_wo = make_pivot(d, "Product", "_mlabel", "write-off_1", divide=1, fmt="{:.2f}")
    pv_lender = make_pivot(d, "lender", "_mlabel", "total_aum", divide=1, fmt="{:.2f}")
    # Monthly Avg AUM from dailyaum
    da = DF.get("daily_aum", pd.DataFrame())
    pv_mavg = pd.DataFrame()
    if not da.empty:
        da2 = filt(da, build_filters({"lender":lender,"Product":product,"channel_type":channel}))
        da2 = add_month_label(da2, "check_month")
        da2 = to_num(da2, ["Total_AUM_1"])
        pv_mavg = make_pivot(da2, "Product", "_mlabel", "Total_AUM_1", divide=1, fmt="{:.2f}")
    # Visual 2.1.1 | table | dzezet | Total AUM
    # Visual 2.1.2 | table | dzezet | GNPA percentage
    # Visual 2.1.3 | table | dzezet | GNPA value
    # Visual 2.1.4 | table | dzezet | Net write-off
    # Visual 2.1.5 | table | dzezet | Lender-wise AUM
    # Visual 2.1.6 | table | fyy6q3 | Monthly average AUM
    return html.Div([
        html.Div([section_title("Total AUM (Cr)"), pivot_table_component(pv_aum, "p1-aum")], className="section-card"),
        html.Div([section_title("GNPA as % of AUM"), pivot_table_component(pv_npa_pct, "p1-npa-pct")], className="section-card"),
        html.Div([section_title("GNPA (90+ PAR) in Cr"), pivot_table_component(pv_npa, "p1-npa")], className="section-card"),
        html.Div([section_title("Net Write-Off (Cr)"), pivot_table_component(pv_wo, "p1-wo")], className="section-card"),
        html.Div([section_title("Lender-wise AUM (Cr)"), pivot_table_component(pv_lender, "p1-lw")], className="section-card"),
        html.Div([section_title("Monthly Avg. AUM (Cr)"), pivot_table_component(pv_mavg, "p1-mavg")], className="section-card"),
    ])

# ===================== PAGE 2: uC (0+PAR) =====================
def page_uc_0par():
    df = DF.get("par", pd.DataFrame())
    return html.Div([
        header_bar("uC Lender: HCPL + 3PL (0+ PAR)"),
        html.Div([
            make_dropdown("Lender", "p2-lender", uvals(df, "lender")),
            make_dropdown("Product", "p2-product", uvals(df, "Product")),
            make_dropdown("Channel Type", "p2-channel", uvals(df, "channel_type")),
            clear_filters_button("p2-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p2-content"),
    ])

@callback(Output("p2-content","children"),
          [Input("p2-lender","value"),Input("p2-product","value"),Input("p2-channel","value")])
@safe_callback
def update_p2(lender, product, channel):
    df = DF.get("par", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Product":product,"channel_type":channel}))
    if d.empty: return empty_state()
    d = add_month_label(d, "check_month")
    d = to_num(d, ["par_0_plus","par_0_plus_cr","par_30_plus","par_60_plus","par_90_plus","total_aum","par_15_plus"])
    pv_0pct = make_pivot(d,"Product","_mlabel","par_0_plus",pct=True,pct_denom="total_aum",fmt="{:.2f}%")
    pv_0val = make_pivot(d,"Product","_mlabel","par_0_plus_cr",divide=1,fmt="{:.2f}")
    # Line chart for 0+ trend
    d["check_date"] = pd.to_datetime(d.get("actual_date", d.get("check_date", pd.Series())), errors="coerce")
    daily = d.groupby("check_date").agg({"par_0_plus":"sum","total_aum":"sum"}).reset_index().dropna(subset=["check_date"]).sort_values("check_date")
    daily["%0+"] = np.where(daily["total_aum"]>0, daily["par_0_plus"]/daily["total_aum"]*100, 0)
    # Visual 2.2.1 | table | gwziy4 | 0+ percentage of AUM
    # Visual 2.2.2 | table | gwziy4 | 0+ PAR value
    # Visual 2.2.3 | chart | gwziy4 | 0+ PAR daily trend
    return html.Div([
        html.Div([section_title("0+ % of AUM"), pivot_table_component(pv_0pct,"p2-pct")], className="section-card"),
        html.Div([section_title("0+ PAR (Cr)"), pivot_table_component(pv_0val,"p2-val")], className="section-card"),
        html.Div([section_title("0+ PAR Daily Trend"), line_chart(daily,"check_date","%0+","0+ as % of AUM",pct=True)], className="section-card"),
    ])

# ===================== PAGE 3: uC (30+ & 60+ PAR) =====================
def page_uc_30_60():
    df = DF.get("book", pd.DataFrame())
    return html.Div([
        header_bar("uC Lender: HCPL + 3PL (30+ & 60+ PAR)"),
        html.Div([
            make_dropdown("Lender", "p3-lender", uvals(df, "lender")),
            make_dropdown("Product", "p3-product", uvals(df, "Product")),
            make_dropdown("Channel Type", "p3-channel", uvals(df, "channel_type")),
            make_dropdown("Bucket Size", "p3-bucket", uvals(df, "bucket_size")),
            clear_filters_button("p3-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p3-content"),
    ])

@callback(Output("p3-content","children"),
          [Input("p3-lender","value"),Input("p3-product","value"),Input("p3-channel","value"),Input("p3-bucket","value")])
@safe_callback
def update_p3(lender, product, channel, bucket):
    df = DF.get("book", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Product":product,"channel_type":channel,"bucket_size":bucket}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["30_plus_par_1","60_plus_par_1","total_aum"])
    pv_30pct = make_pivot(d,"Product","_mlabel","30_plus_par_1",pct=True,pct_denom="total_aum",fmt="{:.2f}%")
    pv_30 = make_pivot(d,"Product","_mlabel","30_plus_par_1",divide=1,fmt="{:.2f}")
    pv_60pct = make_pivot(d,"Product","_mlabel","60_plus_par_1",pct=True,pct_denom="total_aum",fmt="{:.2f}%")
    pv_60 = make_pivot(d,"Product","_mlabel","60_plus_par_1",divide=1,fmt="{:.2f}")
    # Line charts (matching PBI)
    monthly = d.groupby("_mlabel").agg({"30_plus_par_1":"sum","60_plus_par_1":"sum"}).reset_index()
    try:
        monthly["_dt"] = pd.to_datetime(monthly["_mlabel"], format="%b-%y")
        monthly = monthly.sort_values("_dt")
    except: pass
    # Visual 2.3.1 | table | dzezet | 30+ percentage of AUM
    # Visual 2.3.2 | table | dzezet | 30+ PAR value
    # Visual 2.3.3 | chart | dzezet | 30+ PAR trend
    # Visual 2.3.4 | table | dzezet | 60+ percentage of AUM
    # Visual 2.3.5 | table | dzezet | 60+ PAR value
    # Visual 2.3.6 | chart | dzezet | 60+ PAR trend
    return html.Div([
        html.Div([section_title("30+ % of AUM"), pivot_table_component(pv_30pct,"p3-30pct")], className="section-card"),
        html.Div([section_title("30+ PAR (Cr)"), pivot_table_component(pv_30,"p3-30v",highlight_col=True)], className="section-card"),
        html.Div([section_title("30+ PAR Trend"), line_chart(monthly,"_mlabel","30_plus_par_1","30+ PAR (Cr)",BLUE)], className="section-card"),
        html.Div([section_title("60+ % of AUM"), pivot_table_component(pv_60pct,"p3-60pct")], className="section-card"),
        html.Div([section_title("60+ PAR (Cr)"), pivot_table_component(pv_60,"p3-60v",highlight_col=True)], className="section-card"),
        html.Div([section_title("60+ PAR Trend"), line_chart(monthly,"_mlabel","60_plus_par_1","60+ PAR (Cr)",ORANGE)], className="section-card"),
    ])

# ===================== PAGE 4: Daily Trend (0+ to 90+) =====================
def page_daily_trend():
    df = DF.get("par", pd.DataFrame())
    return html.Div([
        header_bar("Daily Trend — 0+ to 90+"),
        html.Div([
            make_dropdown("Lender", "p4-lender", uvals(df, "lender")),
            make_dropdown("Product", "p4-product", uvals(df, "Product")),
            make_dropdown("Channel Type", "p4-channel", uvals(df, "channel_type")),
            make_dropdown("Anchor Tag", "p4-atag", uvals(df, "anchor_tag")),
            clear_filters_button("p4-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p4-content"),
    ])

@callback(Output("p4-content","children"),
          [Input("p4-lender","value"),Input("p4-product","value"),Input("p4-channel","value"),Input("p4-atag","value")])
@safe_callback
def update_p4(lender, product, channel, atag):
    df = DF.get("par", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Product":product,"channel_type":channel,"anchor_tag":atag}))
    if d.empty: return empty_state()
    d = to_num(d, ["par_0_plus_cr","par_15_plus_cr","par_30_plus_cr","par_60_plus_cr","par_90_plus_cr",
                   "total_aum","par_0_plus","par_15_plus","par_30_plus","par_60_plus","par_90_plus"])
    d["check_date"] = pd.to_datetime(d.get("actual_date", d.get("check_date", pd.Series())), errors="coerce")
    d = d.dropna(subset=["check_date"]).sort_values("check_date")
    daily = d.groupby("check_date").agg({
        "par_0_plus_cr":"sum","par_15_plus_cr":"sum","par_30_plus_cr":"sum","par_60_plus_cr":"sum","par_90_plus_cr":"sum",
        "total_aum":"sum","par_0_plus":"sum","par_15_plus":"sum","par_30_plus":"sum","par_60_plus":"sum","par_90_plus":"sum"
    }).reset_index()
    for p in ["0","15","30","60","90"]:
        daily[f"%{p}+"] = np.where(daily["total_aum"]>0, daily[f"par_{p}_plus"]/daily["total_aum"]*100, 0)
    # Visual 2.4.1 | chart | gwziy4 | 0+ PAR value
    # Visual 2.4.2 | chart | gwziy4 | 0+ percentage of AUM
    # Visual 2.4.3 | chart | gwziy4 | 15+ PAR value
    # Visual 2.4.4 | chart | gwziy4 | 15+ percentage of AUM
    # Visual 2.4.5 | chart | gwziy4 | 30+ PAR value
    # Visual 2.4.6 | chart | gwziy4 | 30+ percentage of AUM
    # Visual 2.4.7 | chart | gwziy4 | 60+ PAR value
    # Visual 2.4.8 | chart | gwziy4 | 60+ percentage of AUM
    # Visual 2.4.9 | chart | gwziy4 | 90+ PAR value
    # Visual 2.4.10 | chart | gwziy4 | 90+ percentage of AUM
    charts = []
    colors = [BLUE, DARK_BLUE, ORANGE, "#6B007B", RED]
    for i,(label,vcol,pcol) in enumerate([("0+","par_0_plus_cr","%0+"),("15+","par_15_plus_cr","%15+"),
                                           ("30+","par_30_plus_cr","%30+"),("60+","par_60_plus_cr","%60+"),
                                           ("90+","par_90_plus_cr","%90+")]):
        charts.append(html.Div([
            section_title(f"{label} PAR"),
            html.Div([
                html.Div([line_chart(daily,"check_date",vcol,f"{label} Value (Cr)",colors[i])], style={"flex":"1"}),
                html.Div([line_chart(daily,"check_date",pcol,f"{label} % of AUM",colors[i],pct=True)], style={"flex":"1"}),
            ], className="mobile-visual-stack", style={"display":"flex","gap":"16px"}),
        ], className="section-card"))
    return html.Div(charts)

# ===================== PAGE 5: Daily Trend (PAR values) =====================
def page_daily_par_val():
    df = DF.get("lt_coll", pd.DataFrame())
    return html.Div([
        header_bar("Daily Trend — PAR Values", "All values post write-off"),
        html.Div([
            make_dropdown("Anchor Name", "p5-anchor", uvals(df, "anchor_name")),
            make_dropdown("Anchor Type", "p5-atype", uvals(df, "anchor_type")),
            make_dropdown("Product Type", "p5-product", uvals(df, "product_type")),
            make_dropdown("Org Type", "p5-org", uvals(df, "org_type")),
            make_dropdown("Lender", "p5-lender", uvals(df, "lender")),
            clear_filters_button("p5-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p5-content"),
    ])

@callback(Output("p5-content","children"),
          [Input("p5-anchor","value"),Input("p5-atype","value"),Input("p5-product","value"),
           Input("p5-org","value"),Input("p5-lender","value")])
@safe_callback
def update_p5(anchor, atype, product, org, lender):
    df = DF.get("lt_coll", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"anchor_name":anchor,"anchor_type":atype,"product_type":product,"org_type":org,"lender":lender}))
    if d.empty: return empty_state()
    val_cols = ["par_minus30_M","par_minus30_M_1","par_minus30_M_2","par_minus30_M_3",
                "par_0_M","par_0_M_1","par_0_M_2","par_0_M_3",
                "par_30_M","par_30_M_1","par_30_M_2","par_30_M_3",
                "par_60_M","par_60_M_1","par_60_M_2","par_60_M_3",
                "par_90_M","par_90_M_1","par_90_M_2","par_90_M_3"]
    for vc in val_cols:
        d[vc] = pd.to_numeric(d[vc], errors="coerce")
    d["DayOfMonth"] = pd.to_numeric(d["DayOfMonth"], errors="coerce")
    agg = d.groupby("DayOfMonth")[val_cols].sum().reset_index().sort_values("DayOfMonth")
    # Where a month doesn't have that day (all source values 0/NaN), set to NaN so trace gaps
    for vc in val_cols:
        day_max = d.groupby("DayOfMonth")[vc].max()
        no_data_days = day_max[day_max.fillna(0) == 0].index
        agg.loc[agg["DayOfMonth"].isin(no_data_days), vc] = np.nan
    # Convert raw values to Cr
    for vc in val_cols:
        agg[vc] = agg[vc] / 1e7
    charts_cfg = [
        ("-30 to 0 PAR Movement (Cr)", ["par_minus30_M","par_minus30_M_1","par_minus30_M_2","par_minus30_M_3"]),
        ("1 to 30 PAR Movement (Cr)", ["par_0_M","par_0_M_1","par_0_M_2","par_0_M_3"]),
        ("31 to 60 PAR Movement (Cr)", ["par_30_M","par_30_M_1","par_30_M_2","par_30_M_3"]),
        ("61 to 90 PAR Movement (Cr)", ["par_60_M","par_60_M_1","par_60_M_2","par_60_M_3"]),
        ("91 to 180 PAR Movement (Cr)", ["par_90_M","par_90_M_1","par_90_M_2","par_90_M_3"]),
    ]
    # Visual 2.5.1 | chart | fbtkmw | -30 to 0 PAR movement
    # Visual 2.5.2 | chart | fbtkmw | 1 to 30 PAR movement
    # Visual 2.5.3 | chart | fbtkmw | 31 to 60 PAR movement
    # Visual 2.5.4 | chart | fbtkmw | 61 to 90 PAR movement
    # Visual 2.5.5 | chart | fbtkmw | 91 to 180 PAR movement
    cards = []
    for title, cols in charts_cfg:
        cards.append(html.Div([section_title(title),
            multi_line_chart(agg, "DayOfMonth", cols, title, labels=["M0","M-1","M-2","M-3"])],
            className="section-card"))
    return html.Div(cards)

# ===================== PAGE 6: Daily Trend (PAR count) =====================
def page_daily_par_cnt():
    df = DF.get("lt_coll", pd.DataFrame())
    return html.Div([
        header_bar("Daily Trend — PAR Count Values", "All values post write-off"),
        html.Div([
            make_dropdown("Anchor Name", "p6-ancname", uvals(df, "anchor_name")),
            make_dropdown("Anchor Type", "p6-atype", uvals(df, "anchor_type")),
            make_dropdown("Product Type", "p6-product", uvals(df, "product_type")),
            make_dropdown("Org Type", "p6-org", uvals(df, "org_type")),
            make_dropdown("Lender", "p6-lender", uvals(df, "lender")),
            clear_filters_button("p6-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p6-content"),
    ])

@callback(Output("p6-content","children"),
          [Input("p6-ancname","value"),Input("p6-atype","value"),Input("p6-product","value"),
           Input("p6-org","value"),Input("p6-lender","value")])
@safe_callback
def update_p6(anchor, atype, product, org, lender):
    df = DF.get("lt_coll", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"anchor_name":anchor,"anchor_type":atype,"product_type":product,"org_type":org,"lender":lender}))
    if d.empty: return empty_state()
    cnt_cols = ["par_minus30_M_count","par_minus30_M_1_count","par_minus30_M_2_count","par_minus30_M_3_count",
                "par_0_M_count","par_0_M_1_count","par_0_M_2_count","par_0_M_3_count",
                "par_30_M_count","par_30_M_1_count","par_30_M_2_count","par_30_M_3_count",
                "par_60_M_count","par_60_M_1_count","par_60_M_2_count","par_60_M_3_count",
                "par_90_M_count","par_90_M_1_count","par_90_M_2_count","par_90_M_3_count"]
    for cc in cnt_cols:
        d[cc] = pd.to_numeric(d[cc], errors="coerce")
    d["DayOfMonth"] = pd.to_numeric(d["DayOfMonth"], errors="coerce")
    agg = d.groupby("DayOfMonth")[cnt_cols].sum().reset_index().sort_values("DayOfMonth")
    for cc in cnt_cols:
        day_max = d.groupby("DayOfMonth")[cc].max()
        no_data_days = day_max[day_max.fillna(0) == 0].index
        agg.loc[agg["DayOfMonth"].isin(no_data_days), cc] = np.nan
    charts_cfg = [
        ("-30 to 0 PAR Movement (No)", ["par_minus30_M_count","par_minus30_M_1_count","par_minus30_M_2_count","par_minus30_M_3_count"]),
        ("1 to 30 PAR Movement (No)", ["par_0_M_count","par_0_M_1_count","par_0_M_2_count","par_0_M_3_count"]),
        ("31 to 60 PAR Movement (No)", ["par_30_M_count","par_30_M_1_count","par_30_M_2_count","par_30_M_3_count"]),
        ("61 to 90 PAR Movement (No)", ["par_60_M_count","par_60_M_1_count","par_60_M_2_count","par_60_M_3_count"]),
        ("90+ PAR Movement (No)", ["par_90_M_count","par_90_M_1_count","par_90_M_2_count","par_90_M_3_count"]),
    ]
    # Visual 2.6.1 | chart | fbtkmw | -30 to 0 PAR count
    # Visual 2.6.2 | chart | fbtkmw | 1 to 30 PAR count
    # Visual 2.6.3 | chart | fbtkmw | 31 to 60 PAR count
    # Visual 2.6.4 | chart | fbtkmw | 61 to 90 PAR count
    # Visual 2.6.5 | chart | fbtkmw | 90+ PAR count
    cards = []
    for title, cols in charts_cfg:
        cards.append(html.Div([section_title(title),
            multi_line_chart(agg, "DayOfMonth", cols, title, labels=["M0","M-1","M-2","M-3"])],
            className="section-card"))
    return html.Div(cards)

# ===================== PAGE 7: Anchor (AUM & NPA) =====================
def page_anchor_aum():
    df = DF.get("book", pd.DataFrame())
    return html.Div([
        header_bar("Anchor (AUM & NPA)"),
        html.Div([
            make_dropdown("Lender", "p7-lender", uvals(df, "lender"), multi=False),
            make_dropdown("Anchor", "p7-anchor", uvals(df, "Anchor")),
            make_dropdown("Bucket Size", "p7-bucket", uvals(df, "bucket_size")),
            make_dropdown("Anchor Type", "p7-atype", uvals(df, "Anchor_type")),
            make_dropdown("BD SPOC", "p7-bd", uvals(df, "lead_bd")),
            clear_filters_button("p7-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p7-content"),
    ])

@callback(Output("p7-content","children"),
          [Input("p7-lender","value"),Input("p7-anchor","value"),Input("p7-bucket","value"),Input("p7-atype","value"),Input("p7-bd","value")])
@safe_callback
def update_p7(lender, anchor, bucket, atype, bd):
    df = DF.get("book", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Anchor":anchor,"bucket_size":bucket,"Anchor_type":atype,"lead_bd":bd}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["total_aum","Npa_1","write-off_1"])
    pv_aum = make_pivot(d, "Anchor", "_mlabel", "total_aum", divide=1, fmt="{:.2f}")
    pv_npa_pct = make_pivot(d, "Anchor", "_mlabel", "Npa_1", pct=True, pct_denom="total_aum", fmt="{:.2f}%")
    pv_npa = make_pivot(d, "Anchor", "_mlabel", "Npa_1", divide=1, fmt="{:.2f}")
    pv_wo = make_pivot(d, "Anchor", "_mlabel", "write-off_1", divide=1, fmt="{:.2f}")
    monthly = d.groupby("_mlabel").agg({"total_aum":"sum","Npa_1":"sum"}).reset_index()
    try:
        monthly["_dt"] = pd.to_datetime(monthly["_mlabel"], format="%b-%y")
        monthly = monthly.sort_values("_dt")
    except: pass
    # Visual 2.7.1 | table | dzezet | Anchor AUM
    # Visual 2.7.2 | table | dzezet | Anchor NPA percentage
    # Visual 2.7.3 | table | dzezet | Anchor GNPA value
    # Visual 2.7.4 | table | dzezet | Anchor net write-off
    # Visual 2.7.5 | chart | dzezet | Anchor AUM trend
    # Visual 2.7.6 | chart | dzezet | Anchor NPA trend
    return html.Div([
        html.Div([section_title("Anchor AUM (Cr)"), pivot_table_component(pv_aum,"p7-aum")], className="section-card"),
        html.Div([section_title("NPA % of AUM by Anchor"), pivot_table_component(pv_npa_pct,"p7-npct")], className="section-card"),
        html.Div([section_title("GNPA (90+ PAR) in Cr"), pivot_table_component(pv_npa,"p7-npa")], className="section-card"),
        html.Div([section_title("Net Write-Off (Cr)"), pivot_table_component(pv_wo,"p7-wo")], className="section-card"),
        html.Div([section_title("AUM Trend"), line_chart(monthly,"_mlabel","total_aum","Total AUM (Cr)",BLUE)], className="section-card"),
        html.Div([section_title("NPA Trend"), line_chart(monthly,"_mlabel","Npa_1","90+ PAR (Cr)",RED)], className="section-card"),
    ])

# ===================== PAGE 8: Anchor (lines_count) =====================
def page_anchor_lines():
    df = DF.get("book", pd.DataFrame())
    return html.Div([
        header_bar("Anchor (Lines Count)"),
        html.Div([
            make_dropdown("Lender", "p8-lender", uvals(df, "lender"), multi=False),
            make_dropdown("Anchor", "p8-anchor", uvals(df, "Anchor")),
            make_dropdown("Bucket Size", "p8-bucket", uvals(df, "bucket_size")),
            make_dropdown("Anchor Type", "p8-atype", uvals(df, "Anchor_type")),
            clear_filters_button("p8-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p8-content"),
    ])

@callback(Output("p8-content","children"),
          [Input("p8-lender","value"),Input("p8-anchor","value"),Input("p8-bucket","value"),Input("p8-atype","value")])
@safe_callback
def update_p8(lender, anchor, bucket, atype):
    df = DF.get("book", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Anchor":anchor,"bucket_size":bucket,"Anchor_type":atype}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["count_credit_line_id","count_credit_line_id_disb"])
    pv_cl = make_pivot(d, "Anchor", "_mlabel", "count_credit_line_id", divide=1, fmt="{:.0f}")
    pv_disb = make_pivot(d, "Anchor", "_mlabel", "count_credit_line_id_disb", divide=1, fmt="{:.0f}")
    # Visual 2.8.1 | table | dzezet | Credit lines by anchor
    # Visual 2.8.2 | table | dzezet | Disbursed lines by anchor
    return html.Div([
        html.Div([section_title("#Credit Lines by Anchor"), pivot_table_component(pv_cl,"p8-lc")], className="section-card"),
        html.Div([section_title("#Lines Disbursed by Anchor"), pivot_table_component(pv_disb,"p8-ld")], className="section-card"),
    ])

# ===================== PAGE 9: Anchor (30+ & 60+) =====================
def page_anchor_30_60():
    df = DF.get("book", pd.DataFrame())
    return html.Div([
        header_bar("Anchor (30+ & 60+ PAR)"),
        html.Div([
            make_dropdown("Lender", "p9-lender", uvals(df, "lender"), multi=False),
            make_dropdown("Anchor", "p9-anchor", uvals(df, "Anchor")),
            make_dropdown("Bucket Size", "p9-bucket", uvals(df, "bucket_size")),
            make_dropdown("Anchor Type", "p9-atype", uvals(df, "Anchor_type")),
            clear_filters_button("p9-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p9-content"),
    ])

@callback(Output("p9-content","children"),
          [Input("p9-lender","value"),Input("p9-anchor","value"),Input("p9-bucket","value"),Input("p9-atype","value")])
@safe_callback
def update_p9(lender, anchor, bucket, atype):
    df = DF.get("book", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Anchor":anchor,"bucket_size":bucket,"Anchor_type":atype}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["30_plus_par_1","60_plus_par_1","Npa_1","total_aum"])
    pv30_pct = make_pivot(d,"Anchor","_mlabel","30_plus_par_1",pct=True,pct_denom="total_aum",fmt="{:.2f}%")
    pv30_val = make_pivot(d,"Anchor","_mlabel","30_plus_par_1",divide=1,fmt="{:.2f}")
    pv60_pct = make_pivot(d,"Anchor","_mlabel","60_plus_par_1",pct=True,pct_denom="total_aum",fmt="{:.2f}%")
    pv60_val = make_pivot(d,"Anchor","_mlabel","60_plus_par_1",divide=1,fmt="{:.2f}")
    monthly = d.groupby("_mlabel").agg({"Npa_1":"sum"}).reset_index()
    try:
        monthly["_dt"] = pd.to_datetime(monthly["_mlabel"], format="%b-%y")
        monthly = monthly.sort_values("_dt")
    except: pass
    # Visual 2.9.1 | table | dzezet | Anchor 30+ percentage
    # Visual 2.9.2 | table | dzezet | Anchor 30+ value
    # Visual 2.9.3 | table | dzezet | Anchor 60+ percentage
    # Visual 2.9.4 | table | dzezet | Anchor 60+ value
    # Visual 2.9.5 | chart | dzezet | Anchor 90+ trend
    return html.Div([
        html.Div([section_title("30+ % of AUM by Anchor"), pivot_table_component(pv30_pct,"p9-30p")], className="section-card"),
        html.Div([section_title("30+ PAR (Cr) by Anchor"), pivot_table_component(pv30_val,"p9-30v")], className="section-card"),
        html.Div([section_title("60+ % of AUM by Anchor"), pivot_table_component(pv60_pct,"p9-60p")], className="section-card"),
        html.Div([section_title("60+ PAR (Cr) by Anchor"), pivot_table_component(pv60_val,"p9-60v")], className="section-card"),
        html.Div([section_title("90+ PAR Trend"), line_chart(monthly,"_mlabel","Npa_1","90+ PAR (Cr)",RED)], className="section-card"),
    ])

# ===================== PAGE 10: Anchor (Disbursals & #lines) =====================
def page_anchor_disb():
    df = DF.get("book", pd.DataFrame())
    return html.Div([
        header_bar("Anchor (Disbursals & #Lines)"),
        html.Div([
            make_dropdown("Lender", "p10-lender", uvals(df, "lender"), multi=False),
            make_dropdown("Anchor", "p10-anchor", uvals(df, "Anchor")),
            make_dropdown("Bucket Size", "p10-bucket", uvals(df, "bucket_size")),
            make_dropdown("Anchor Type", "p10-atype", uvals(df, "Anchor_type")),
            make_dropdown("BD SPOC", "p10-bd", uvals(df, "lead_bd")),
            clear_filters_button("p10-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p10-content"),
    ])

@callback(Output("p10-content","children"),
          [Input("p10-lender","value"),Input("p10-anchor","value"),Input("p10-bucket","value"),Input("p10-atype","value"),Input("p10-bd","value")])
@safe_callback
def update_p10(lender, anchor, bucket, atype, bd):
    df = DF.get("book", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Anchor":anchor,"bucket_size":bucket,"Anchor_type":atype,"lead_bd":bd}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["Disbursal_amt","count_credit_line_id_disb"])
    pv_disb = make_pivot(d, "Anchor", "_mlabel", "Disbursal_amt", divide=1, fmt="{:.2f}")
    pv_lines = make_pivot(d, "Anchor", "_mlabel", "count_credit_line_id", divide=1, fmt="{:.0f}")
    monthly = d.groupby("_mlabel").agg({"Disbursal_amt":"sum"}).reset_index()
    try:
        monthly["_dt"] = pd.to_datetime(monthly["_mlabel"], format="%b-%y")
        monthly = monthly.sort_values("_dt")
    except: pass
    # Visual 2.10.1 | table | dzezet | Disbursal amount by anchor
    # Visual 2.10.2 | table | dzezet | Credit lines by anchor
    # Visual 2.10.3 | chart | dzezet | Disbursal trend
    return html.Div([
        html.Div([section_title("Disbursal Amount (Cr)"), pivot_table_component(pv_disb,"p10-d")], className="section-card"),
        html.Div([section_title("#Credit Lines by Anchor"), pivot_table_component(pv_lines,"p10-l")], className="section-card"),
        html.Div([section_title("Disbursal Trend"), line_chart(monthly,"_mlabel","Disbursal_amt","Disbursal Amount (Cr)",BLUE)], className="section-card"),
    ])

# ===================== PAGE 11: Brand Anchors (AUM & NPA) =====================
def page_brand_anchor():
    df = DF.get("book", pd.DataFrame())
    return html.Div([
        header_bar("Brand Anchors (AUM & NPA)"),
        html.Div([
            make_dropdown("Lender", "p11-lender", uvals(df, "lender"), multi=False),
            make_dropdown("Anchor", "p11-anchor", uvals(df, "Anchors")),
            make_dropdown("Bucket Size", "p11-bucket", uvals(df, "bucket_size")),
            make_dropdown("Anchor Type", "p11-atype", uvals(df, "Anchor_type")),
            make_dropdown("Anchor Category", "p11-cat", uvals(df, "anchor_category")),
            clear_filters_button("p11-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p11-content"),
    ])

@callback(Output("p11-content","children"),
          [Input("p11-lender","value"),Input("p11-anchor","value"),Input("p11-bucket","value"),Input("p11-atype","value"),Input("p11-cat","value")])
@safe_callback
def update_p11(lender, anchor, bucket, atype, cat):
    df = DF.get("book", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Anchors":anchor,"bucket_size":bucket,"Anchor_type":atype,"anchor_category":cat}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["total_aum","Npa_1","write-off_1","Disbursal_amt"])
    pv_aum = make_pivot(d, "Anchors", "_mlabel", "total_aum", divide=1, fmt="{:.2f}")
    pv_npa_pct = make_pivot(d, "Anchors", "_mlabel", "Npa_1", pct=True, pct_denom="total_aum", fmt="{:.2f}%")
    pv_npa = make_pivot(d, "Anchors", "_mlabel", "Npa_1", divide=1, fmt="{:.2f}")
    pv_wo = make_pivot(d, "Anchors", "_mlabel", "write-off_1", divide=1, fmt="{:.2f}")
    pv_disb = make_pivot(d, "Anchors", "_mlabel", "Disbursal_amt", divide=1, fmt="{:.2f}")
    monthly = d.groupby("_mlabel").agg({"total_aum":"sum","Npa_1":"sum"}).reset_index()
    try:
        monthly["_dt"] = pd.to_datetime(monthly["_mlabel"], format="%b-%y")
        monthly = monthly.sort_values("_dt")
    except: pass
    # Visual 2.11.1 | table | dzezet | Brand anchor AUM
    # Visual 2.11.2 | table | dzezet | Brand anchor NPA percentage
    # Visual 2.11.3 | table | dzezet | Brand anchor GNPA
    # Visual 2.11.4 | table | dzezet | Brand anchor write-off
    # Visual 2.11.5 | table | dzezet | Brand anchor disbursal
    # Visual 2.11.6 | chart | dzezet | Brand anchor AUM trend
    # Visual 2.11.7 | chart | dzezet | Brand anchor NPA trend
    return html.Div([
        html.Div([section_title("Brand Anchor AUM (Cr)"), pivot_table_component(pv_aum,"p11-a")], className="section-card"),
        html.Div([section_title("NPA % of AUM"), pivot_table_component(pv_npa_pct,"p11-npct")], className="section-card"),
        html.Div([section_title("GNPA (90+ PAR) in Cr"), pivot_table_component(pv_npa,"p11-n")], className="section-card"),
        html.Div([section_title("Net Write-Off (Cr)"), pivot_table_component(pv_wo,"p11-wo")], className="section-card"),
        html.Div([section_title("Disbursal Amount (Cr)"), pivot_table_component(pv_disb,"p11-d")], className="section-card"),
        html.Div([section_title("AUM Trend"), line_chart(monthly,"_mlabel","total_aum","Total AUM (Cr)",BLUE)], className="section-card"),
        html.Div([section_title("NPA Trend"), line_chart(monthly,"_mlabel","Npa_1","90+ PAR (Cr)",RED)], className="section-card"),
    ])

# ===================== PAGE 12: L30 Day Anchor AUM =====================
def page_l30_anchor():
    df = DF.get("l30", pd.DataFrame())
    return html.Div([
        header_bar("L30 Day Anchor AUM"),
        html.Div([
            make_dropdown("Lender", "p12-lender", uvals(df, "lender")),
            make_dropdown("Product", "p12-product", uvals(df, "product_type")),
            make_dropdown("Anchor Type", "p12-atype", uvals(df, "anchor_type")),
            make_dropdown("Bucket Size", "p12-bucket", uvals(df, "bucket_size")),
            clear_filters_button("p12-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p12-content"),
    ])

@callback(Output("p12-content","children"),
          [Input("p12-lender","value"),Input("p12-product","value"),Input("p12-atype","value"),Input("p12-bucket","value")])
@safe_callback
def update_p12(lender, product, atype, bucket):
    df = DF.get("l30", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"product_type":product,"anchor_type":atype,"bucket_size":bucket}))
    if d.empty: return empty_state()
    d = to_num(d, ["AUM","Npa","AUM_latest"])
    d["Check_date"] = pd.to_datetime(d["Check_date"], errors="coerce")
    d["_dlabel"] = d["Check_date"].dt.strftime("%d-%b")
    pv = make_pivot(d, "anchor", "_dlabel", "AUM", divide=1, fmt="{:.2f}")
    # Pending visual 2.12.1 | table | source not configured | L30 Anchor AUM
    return html.Div([
        html.Div([section_title("L30 Anchor AUM (Cr)"), pivot_table_component(pv,"p12-a")], className="section-card"),
    ])

# ===================== PAGE 13: Pratishtha DPD View =====================
def page_pratishtha():
    df = DF.get("dpd", pd.DataFrame())
    return html.Div([
        header_bar("Pratishtha DPD View"),
        html.Div([
            make_dropdown("DPD Bucket", "p13-dpd", uvals(df, "dpd_bucket")),
            make_dropdown("Lender", "p13-lender", uvals(df, "lender")),
            make_dropdown("Org Type", "p13-org", uvals(df, "org_type")),
            make_dropdown("AUM Flag", "p13-flag", uvals(df, "aum_flag")),
            clear_filters_button("p13-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p13-content"),
    ])

@callback(Output("p13-content","children"),
          [Input("p13-dpd","value"),Input("p13-lender","value"),Input("p13-org","value"),Input("p13-flag","value")])
@safe_callback
def update_p13(dpd, lender, org, flag):
    df = DF.get("dpd", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"dpd_bucket":dpd,"lender":lender,"org_type":org,"aum_flag":flag}))
    if d.empty: return empty_state()
    bv_col = "book_value" if "book_value" in d.columns else "due_amount" if "due_amount" in d.columns else "aum"
    d = to_num(d, [bv_col])
    d[bv_col] = d[bv_col] / 1e7 if d[bv_col].max() > 1e6 else d[bv_col]
    d["check_date"] = pd.to_datetime(d.get("checkdate", d.get("check_date", pd.Series())), errors="coerce")
    d["_dlabel"] = d["check_date"].dt.strftime("%d-%b-%y")
    pv_lender = make_pivot(d, "lender", "_dlabel", bv_col, divide=1, fmt="{:.2f}")
    pv_org = make_pivot(d, "org_type", "_dlabel", bv_col, divide=1, fmt="{:.2f}")
    pv_dpd = make_pivot(d, "dpd_bucket", "_dlabel", bv_col, divide=1, fmt="{:.2f}")
    # Visual 2.13.1 | table | dv2jpb | Book value by lender
    # Visual 2.13.2 | table | dv2jpb | Book value by organisation type
    # Visual 2.13.3 | table | dv2jpb | Book value by DPD bucket
    return html.Div([
        html.Div([section_title("Book Value (Cr) by Lender"), pivot_table_component(pv_lender,"p13-l")], className="section-card"),
        html.Div([section_title("Book Value (Cr) by Org Type"), pivot_table_component(pv_org,"p13-o")], className="section-card"),
        html.Div([section_title("Book Value (Cr) by DPD Bucket"), pivot_table_component(pv_dpd,"p13-d")], className="section-card"),
    ])

# ===================== PAGE 14: Intercompany =====================
def page_intercompany():
    df = DF.get("interco", pd.DataFrame())
    return html.Div([
        header_bar("Intercompany"),
        html.Div([
            make_dropdown("Lender", "p14-lender", uvals(df, "lender")),
            make_dropdown("Product", "p14-product", uvals(df, "product_type")),
            make_dropdown("Anchor", "p14-anchor", uvals(df, "anchor")[:80]),
            make_dropdown("Bucket Size", "p14-bucket", uvals(df, "bucket_size")),
            clear_filters_button("p14-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p14-content"),
    ])

@callback(Output("p14-content","children"),
          [Input("p14-lender","value"),Input("p14-product","value"),Input("p14-anchor","value"),Input("p14-bucket","value")])
@safe_callback
def update_p14(lender, product, anchor, bucket):
    df = DF.get("interco", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"product_type":product,"anchor":anchor,"bucket_size":bucket}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["AUM"])
    d["AUM_cr"] = d["AUM"] / 1e7 if d["AUM"].max() > 1e6 else d["AUM"]
    # PBI: pivot by borrower_name (rows), credit_line_id also shown, month (cols) → Total_aum
    pv_aum = make_pivot(d, "borrower_name", "_mlabel", "AUM_cr", divide=1, fmt="{:.2f}")
    # Visual 2.14.1 | table | f73jfw | Intercompany AUM
    return html.Div([
        html.Div([section_title("Intercompany AUM (Cr)"), pivot_table_component(pv_aum,"p14-a")], className="section-card"),
    ])

# ===================== PAGE 15: Max Exact DPD Data =====================
P15_FILTER_IDS = [
    "p15-orgid", "p15-orgname", "p15-category", "p15-maxdpd1",
    "p15-zone", "p15-loantype", "p15-reportmonth", "p15-maxdpd",
    "p15-state", "p15-bim", "p15-spoc", "p15-city",
]
P15_COLUMN_MAP = {
    "report_month": "Month", "org_id": "Org ID", "org_name": "org_name",
    "loan_type": "loan_type", "category": "category", "zone": "zone",
    "max_dpd": "max_dpd", "credit_limit": "credit_limit", "amt_os": "POS",
    "total_due": "Due", "due_0_7": "Due(0-7)", "due_8_15": "Due(8-15)",
    "due_16_30": "Due(16-30)", "due_31_60": "Due(31-60)",
    "due_61_90": "Due(61-90)", "due_91_180": "Due(91-180)",
    "due_180_plus": "Due(180+)",
}


def _p15_filtered_export(
    org_id, org_name, category, max_dpd1, zone, loan_type,
    report_month, max_dpd, state, bim, spoc, city,
):
    df = DF.get("exact_dpd", pd.DataFrame())
    if df.empty:
        return pd.DataFrame()
    result = filt(df, build_filters({
        "org_id": org_id, "org_name": org_name, "category": category,
        "zone": zone, "loan_type": loan_type, "report_month": report_month,
        "state": state, "bim": bim, "spoc": spoc, "city": city,
    }))
    # The PBIT contains two slicers over the same physical max_dpd column.
    # Apply each independently so selecting both produces their intersection.
    result = filt(result, build_filters({"max_dpd": max_dpd1}))
    result = filt(result, build_filters({"max_dpd": max_dpd}))
    if result.empty:
        return result
    dimensions = [
        "report_month", "org_id", "org_name", "loan_type", "category",
        "zone", "max_dpd", "credit_limit",
    ]
    measures = [
        "amt_os", "total_due", "due_0_7", "due_8_15", "due_16_30",
        "due_31_60", "due_61_90", "due_91_180", "due_180_plus",
    ]
    available_dimensions = [column for column in dimensions if column in result.columns]
    available_measures = [column for column in measures if column in result.columns]
    result = to_num(result, available_measures, copy=True)
    if available_dimensions and available_measures:
        result = (
            result.groupby(available_dimensions, dropna=False, sort=False)[available_measures]
            .sum(min_count=1)
            .reset_index()
        )
    if "report_month" in result.columns:
        result = result.sort_values("report_month", ascending=False, kind="stable")
    columns = [column for column in P15_COLUMN_MAP if column in result.columns]
    return result[columns].rename(columns=P15_COLUMN_MAP)


def page_dpd_data():
    df = DF.get("exact_dpd", pd.DataFrame())
    return html.Div([
        header_bar("Max Exact DPD Data", "Product wise max DPD bucket — not indicative of current dues"),
        html.Div([
            make_dropdown("org_id", "p15-orgid", uvals(df, "org_id")),
            make_dropdown("org_name", "p15-orgname", uvals(df, "org_name")),
            make_dropdown("category", "p15-category", uvals(df, "category")),
            make_dropdown("max_dpd1", "p15-maxdpd1", uvals(df, "max_dpd")),
            make_dropdown("zone", "p15-zone", uvals(df, "zone")),
            make_dropdown("loan_type", "p15-loantype", uvals(df, "loan_type")),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "8px"}),
        html.Div([
            make_dropdown("report_month", "p15-reportmonth", uvals(df, "report_month")),
            make_dropdown("max_dpd", "p15-maxdpd", uvals(df, "max_dpd")),
            make_dropdown("state", "p15-state", uvals(df, "state")),
            make_dropdown("bim", "p15-bim", uvals(df, "bim")),
            make_dropdown("spoc", "p15-spoc", uvals(df, "spoc")),
            make_dropdown("city", "p15-city", uvals(df, "city")),
            clear_filters_button("p15-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        full_export_controls("p15-export-all", "p15-download-all"),
        html.Div(id="p15-content"),
    ])

@callback(Output("p15-content","children"),
          [Input("p15-orgid","value"),Input("p15-orgname","value"),
           Input("p15-category","value"),Input("p15-maxdpd1","value"),
           Input("p15-zone","value"),Input("p15-loantype","value"),
           Input("p15-reportmonth","value"),Input("p15-maxdpd","value"),
           Input("p15-state","value"),Input("p15-bim","value"),
           Input("p15-spoc","value"),Input("p15-city","value")])
@safe_callback
def update_p15(org_id, org_name, category, max_dpd1, zone, loan_type,
               report_month, max_dpd, state, bim, spoc, city):
    d = _p15_filtered_export(
        org_id, org_name, category, max_dpd1, zone, loan_type,
        report_month, max_dpd, state, bim, spoc, city,
    )
    if d.empty: return empty_state()
    display = d.head(500).copy()
    for nc in ["credit_limit", "POS", "Due", "Due(0-7)", "Due(8-15)",
               "Due(16-30)", "Due(31-60)", "Due(61-90)", "Due(91-180)", "Due(180+)"]:
        if nc in display.columns:
            display[nc] = display[nc].apply(lambda x: f"{x:,.0f}" if pd.notna(x) and x != 0 else "")
    # Visual 2.15.1 | table | di6x4p | Max exact DPD detail
    return html.Div([
        html.Div([section_title(f"Max Exact DPD Data ({len(d):,} rows, showing first 500)"),
            html.P("Note: This View shows the product wise maximum DPD bucket that a seller went into in a particular month. It is not indicative of current dues",
                   style={"fontSize":"11px","color":TEXT_LIGHT,"marginBottom":"8px"}),
            table_ui(display, component_id="p15-detail-table", page_size=50,
                     filterable=True, downloadable=False)], className="section-card"),
    ])


@callback(
    Output("p15-download-all", "data"),
    Input("p15-export-all", "n_clicks"),
    [State(component_id, "value") for component_id in P15_FILTER_IDS],
    prevent_initial_call=True,
)
def export_p15_all(_n_clicks, *values):
    export = _p15_filtered_export(*values)
    if export.empty:
        return no_update
    return dcc.send_data_frame(export.to_csv, "max_exact_dpd_filtered.csv", index=False)

# ===================== PAGE 16: uC AUM & NPA (Internal) =====================
def page_uc_internal():
    df = DF.get("dupe", pd.DataFrame())
    return html.Div([
        header_bar("uC AUM & NPA (Internal)"),
        html.Div([
            make_dropdown("Lender", "p16-lender", uvals(df, "lender")),
            make_dropdown("Product", "p16-product", uvals(df, "Product_x")),
            make_dropdown("Anchor", "p16-anchor", uvals(df, "anchor")[:80]),
            make_dropdown("Bucket Size", "p16-bucket", uvals(df, "bucket_size")),
            make_dropdown("Anchor Type", "p16-atype", uvals(df, "anchor_type")),
            make_dropdown("RSM", "p16-rsm", uvals(df, "rsm")),
            clear_filters_button("p16-clear"),
        ], style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "16px"}),
        html.Div(id="p16-content"),
    ])

@callback(Output("p16-content","children"),
          [Input("p16-lender","value"),Input("p16-product","value"),Input("p16-anchor","value"),
           Input("p16-bucket","value"),Input("p16-atype","value"),Input("p16-rsm","value")])
@safe_callback
def update_p16(lender, product, anchor, bucket, atype, rsm):
    df = DF.get("dupe", pd.DataFrame())
    if df.empty: return empty_state()
    d = filt(df, build_filters({"lender":lender,"Product_x":product,"anchor":anchor,"bucket_size":bucket,"anchor_type":atype,"rsm":rsm}))
    if d.empty: return empty_state()
    d = add_month_label(d)
    d = to_num(d, ["total_aum_x","Npa_90_270","write_off"])
    d["write_off_cr"] = d["write_off"] / 1e7 if "write_off" in d.columns and d["write_off"].max() > 1e6 else d.get("write_off", 0)
    pv_aum = make_pivot(d, "Product_x", "_mlabel", "total_aum_x", divide=1, fmt="{:.2f}")
    pv_lender = make_pivot(d, "lender", "_mlabel", "total_aum_x", divide=1, fmt="{:.2f}")
    pv_npa = make_pivot(d, "Product_x", "_mlabel", "Npa_90_270", divide=1, fmt="{:.2f}")
    pv_pct = make_pivot(d, "Product_x", "_mlabel", "Npa_90_270", pct=True, pct_denom="total_aum_x", fmt="{:.2f}%")
    pv_wo = make_pivot(d, "Product_x", "_mlabel", "write_off_cr", divide=1, fmt="{:.2f}")
    # Monthly Avg AUM from dailyaum
    da = DF.get("daily_aum", pd.DataFrame())
    pv_mavg = pd.DataFrame()
    if not da.empty:
        da2 = filt(da, build_filters({"lender":lender,"Product":product}))
        da2 = add_month_label(da2, "check_month")
        da2 = to_num(da2, ["Total_AUM_1"])
        pv_mavg = make_pivot(da2, "Product", "_mlabel", "Total_AUM_1", divide=1, fmt="{:.2f}")
    # Visual 2.16.1 | table | fyy6q3 | Monthly average AUM
    # Visual 2.16.2 | table | otxlat | Internal AUM by product
    # Visual 2.16.3 | table | otxlat | Internal lender-wise AUM
    # Visual 2.16.4 | table | otxlat | Internal NPA percentage
    # Visual 2.16.5 | table | otxlat | Internal NPA value
    # Visual 2.16.6 | table | otxlat | Internal net write-off
    return html.Div([
        html.Div([section_title("Monthly Avg. AUM (Cr)"), pivot_table_component(pv_mavg,"p16-mavg")], className="section-card"),
        html.Div([section_title("Total AUM (Cr) by Product"), pivot_table_component(pv_aum,"p16-a")], className="section-card"),
        html.Div([section_title("Lender-wise AUM (Cr)"), pivot_table_component(pv_lender,"p16-lw")], className="section-card"),
        html.Div([section_title("NPA 90-270 % of AUM"), pivot_table_component(pv_pct,"p16-p")], className="section-card"),
        html.Div([section_title("NPA 90-270 (Cr)"), pivot_table_component(pv_npa,"p16-n")], className="section-card"),
        html.Div([section_title("Net Write-Off (Cr)"), pivot_table_component(pv_wo,"p16-wo")], className="section-card"),
    ])

# ===================== ROUTING =====================
@callback(Output("page-content","children"), Input("url","pathname"))
def route(path):
    p = (path or "/").strip("/")
    page_datasets = {
        "uc-aum-npa": ("book", "daily_aum"),
        "uc-0par": ("par",),
        "uc-30-60": ("book",),
        "daily-trend": ("par",),
        "daily-par-val": ("lt_coll",),
        "daily-par-cnt": ("lt_coll",),
        "anchor-aum": ("book",),
        "anchor-lines": ("book",),
        "anchor-30-60": ("book",),
        "anchor-disb": ("book",),
        "brand-anchor": ("book",),
        "pratishtha": ("dpd",),
        "intercompany": ("interco",),
        "dpd-data": ("exact_dpd",),
        "uc-internal": ("dupe", "daily_aum"),
    }
    for dataset in page_datasets.get(p or "uc-aum-npa", ("book", "daily_aum")):
        _ensure_dataset(dataset)
    pages = {
        "uc-aum-npa": page_uc_aum_npa,
        "uc-0par": page_uc_0par,
        "uc-30-60": page_uc_30_60,
        "daily-trend": page_daily_trend,
        "daily-par-val": page_daily_par_val,
        "daily-par-cnt": page_daily_par_cnt,
        "anchor-aum": page_anchor_aum,
        "anchor-lines": page_anchor_lines,
        "anchor-30-60": page_anchor_30_60,
        "anchor-disb": page_anchor_disb,
        "brand-anchor": page_brand_anchor,
        "l30-anchor": page_l30_anchor,
        "pratishtha": page_pratishtha,
        "intercompany": page_intercompany,
        "dpd-data": page_dpd_data,
        "uc-internal": page_uc_internal,
    }
    fn = pages.get(p, page_uc_aum_npa)
    try:
        return fn()
    except Exception as e:
        import traceback; traceback.print_exc(file=sys.stderr)
        return html.Div(f"Error loading page: {e}", style={"color": RED, "padding": "30px"})
