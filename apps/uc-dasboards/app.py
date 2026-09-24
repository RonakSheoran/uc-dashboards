"""uC Dashboards — merged single-app shell."""
import dash
from dash import html, dcc, callback, Output, Input, ctx, no_update
import dash_bootstrap_components as dbc

# Import all dashboard modules so their callbacks are registered.
import uc_live
import relationship
import aum_dashboard
import operational_metrics
import lt_sales
import portfolio_monitoring
import invoice_command
import decisioning_command
from shared import start_global_refresh_scheduler, track_tab_click
from ui import APP_CONFIG, NAVIGATION, REFRESH_CONFIG, theme_value, theme_css_variables

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PAGES = sorted(NAVIGATION["dashboards"], key=lambda item: item.get("order", 0))
PAGE_IDS = [item["id"] for item in PAGES]
DEFAULT_PAGE = APP_CONFIG.get("default_dashboard", PAGE_IDS[0])
PAGE_MODULES = {
    "live": uc_live,
    "relationship": relationship,
    "aum": aum_dashboard,
    "operations": operational_metrics,
    "lt_sales": lt_sales,
    "portfolio": portfolio_monitoring,
    "invoice_command": invoice_command,
    "decisioning_command": decisioning_command,
}
DEFAULT_TABS = {
    page["id"]: (
        sorted(NAVIGATION.get("subpages", {}).get(page["id"], []), key=lambda item: item.get("order", 0))[0]["id"]
        if NAVIGATION.get("subpages", {}).get(page["id"]) else "main"
    )
    for page in PAGES
}

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------
SIDEBAR_W = 250
SIDEBAR_CW = 56

SIDEBAR_EXPANDED = {
    "background": "#343a40", "padding": "20px 15px", "width": f"{SIDEBAR_W}px",
    "position": "fixed", "top": 0, "left": 0, "bottom": 0,
    "overflowY": "auto", "zIndex": 10, "transition": "width .2s ease",
}
SIDEBAR_COLLAPSED = {**SIDEBAR_EXPANDED, "width": f"{SIDEBAR_CW}px", "padding": "20px 6px"}

BTN_BASE = {
    "width": "100%", "padding": "14px", "marginBottom": "8px",
    "borderRadius": "8px", "border": "none", "color": "white",
    "fontWeight": "bold", "fontSize": "16px", "cursor": "pointer",
    "transition": "background .15s", "whiteSpace": "nowrap", "overflow": "hidden",
    "textAlign": "left",
}
BTN_ACTIVE   = {**BTN_BASE, "background": theme_value("colors.primary", "#dc3545")}
BTN_INACTIVE = {**BTN_BASE, "background": "#343a40"}

CONTENT_EXPANDED  = {"marginLeft": f"{SIDEBAR_W}px", "padding": "0", "background": "#f7f7fa", "minHeight": "100vh", "transition": "margin-left .2s ease"}
CONTENT_COLLAPSED = {**CONTENT_EXPANDED, "marginLeft": f"{SIDEBAR_CW}px"}

TOGGLE = {"background": "transparent", "border": "none", "color": "#dc3545",
          "fontSize": "22px", "cursor": "pointer", "padding": "6px 8px",
          "borderRadius": "6px", "width": "100%", "textAlign": "center", "marginBottom": "10px"}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap",
        "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap",
    ],
    suppress_callback_exceptions=True,
)
app.title = APP_CONFIG.get("title", "uC Dashboards")
server = app.server

# Inject CSS that was originally in each app's index_string
app.index_string = '''<!DOCTYPE html>
<html>
<head>
{%metas%}<title>{%title%}</title>{%favicon%}{%css%}
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
</head>
<body>
{%app_entry%}
<footer>{%config%}{%scripts%}{%renderer%}</footer>
</body>
</html>'''

app.layout = html.Div([
    dcc.Store(id="shell-active-page", data=DEFAULT_PAGE),
    dcc.Store(id="shell-sb-open", data=True),

    # Global callback activity indicator. CSS watches Dash's loading attribute so
    # page changes, tab changes, filters, tables, charts and refreshes all use it.
    html.Div([
        html.Div(className="global-loading-spinner"),
        html.Div("Loading dashboard…", className="global-loading-text"),
    ], id="global-loading-indicator", className="global-loading-indicator",
       role="status", **{"aria-live": "polite", "aria-label": "Dashboard is loading"}),

    # Sidebar
    html.Div([
        html.Button("\u2630", id="shell-toggle", n_clicks=0, style=TOGGLE),
        html.H2("Dashboards", id="shell-title", style={"color": "#dc3545", "marginBottom": "1rem", "fontSize": "18px"}),
        html.Hr(id="shell-hr", style={"borderColor": "#dc3545"}),
        html.Div([
            html.Button(
                [html.Img(src=f"/assets/nav-icons/{page.get('icon', page['id'] + '.svg')}", className=f"shell-nav-icon shell-nav-icon--{page['id']}", alt="", title=page["label"]),
                 html.Span(page["label"], id=f"shell-lbl-{i}")],
                id=f"shell-btn-{i}", n_clicks=0,
                style=BTN_ACTIVE if i == 0 else BTN_INACTIVE,
            ) for i, page in enumerate(PAGES)
        ]),
    ], id="shell-sidebar", className="shell-sidebar shell-sidebar--expanded",
       style=SIDEBAR_EXPANDED),

    # Content
    html.Div(id="shell-content", style=CONTENT_EXPANDED),
], style=theme_css_variables())


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
@callback(
    Output("shell-active-page", "data"),
    [Input(f"shell-btn-{i}", "n_clicks") for i in range(len(PAGES))],
    prevent_initial_call=True,
)
def on_sidebar_click(*_):
    tid = ctx.triggered_id
    if tid is None:
        return no_update
    idx = int(tid.split("-")[-1])
    page_id = PAGES[idx]["id"]
    track_tab_click(page_id, DEFAULT_TABS[page_id])
    return page_id


@callback(
    [Output(f"shell-btn-{i}", "style") for i in range(len(PAGES))],
    Input("shell-active-page", "data"),
)
def highlight_btn(active):
    return [BTN_ACTIVE if page["id"] == active else BTN_INACTIVE for page in PAGES]


@callback(
    Output("shell-sb-open", "data"),
    Input("shell-toggle", "n_clicks"),
    Input("shell-sb-open", "data"),
    prevent_initial_call=True,
)
def toggle_sidebar(_, is_open):
    return not is_open


@callback(
    [Output("shell-sidebar", "style"), Output("shell-content", "style"),
     Output("shell-title", "style"), Output("shell-hr", "style")]
    + [Output(f"shell-lbl-{i}", "style") for i in range(len(PAGES))]
    + [Output("shell-sidebar", "className")],
    Input("shell-sb-open", "data"),
)
def apply_collapse(is_open):
    lbl = {"display": "inline"} if is_open else {"display": "none"}
    if is_open:
        return [SIDEBAR_EXPANDED, CONTENT_EXPANDED,
                {"color": "#dc3545", "marginBottom": "1rem", "fontSize": "18px"},
                {"borderColor": "#dc3545"}] + [lbl] * len(PAGES) + ["shell-sidebar shell-sidebar--expanded"]
    return [SIDEBAR_COLLAPSED, CONTENT_COLLAPSED,
            {"display": "none"}, {"display": "none"}] + [lbl] * len(PAGES) + ["shell-sidebar shell-sidebar--collapsed"]


@callback(
    Output("shell-content", "children"),
    Input("shell-active-page", "data"),
)
def render_section(active):
    module = PAGE_MODULES.get(active)
    return module.layout() if module else html.Div("Select a page from the sidebar.")


# All modules perform an initial data load during import (deployment). This one
# process-wide scheduler refreshes every module again at the configured IST
# times, independently of which pages users have open.
start_global_refresh_scheduler(
    REFRESH_CONFIG,
    {
        "live": uc_live.refresh_data,
        "aum": aum_dashboard.refresh_data,
        "relationship": relationship.refresh_data,
        "operations": operational_metrics.refresh_data,
        "lt_sales": lt_sales.refresh_data,
        "portfolio": portfolio_monitoring.refresh_data,
        "invoice_command": invoice_command.refresh_data,
        "decisioning_command": decisioning_command.refresh_data,
    },
)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
