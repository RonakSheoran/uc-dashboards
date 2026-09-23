# Maintaining uC Dashboards

## Opt-in matrix cross-filtering

`ui/cross_filter.py` contains the reusable matrix-to-detail helpers. A page must
explicitly wire a matrix `active_cell` into a `dcc.Store`, call
`matrix_cell_selection(...)`, and apply the stored cohort with
`apply_matrix_selection(...)`. This is intentionally not enabled by the global
table component because every enabled matrix adds callback work. At present,
only Operational Metrics → Anchor Current State uses it.

The project has shared UI and data layers. Business calculations remain in the
dashboard modules, while appearance, navigation, SQL access and common pandas
transformations are centrally controlled.

## Common changes

| Change | Edit |
|---|---|
| Colour, typography, chart palette or table defaults | `config/theme.json` |
| Dashboard/sidebar name, icon or order | `config/navigation.json` |
| AUM, Relationship or Operations tab name/order | `config/navigation.json` |
| Refresh schedule | `config/refresh.json` |
| Table suffix → full Databricks table | `config/tables.json` |
| Visual identifier → table suffixes | `config/visual_lineage.json` |
| Business ordering for pivot columns | `config/column_order.json` |
| Shared table/chart/filter/header behavior | `ui/components.py` |
| SQL connection, query execution or TTL cache behavior | `shared/db.py` |
| Filtering, numeric conversion or pivot behavior | `shared/frames.py` |
| Business calculation | Relevant dashboard module or upstream SQL |

Run this before deployment:

```bash
python tools/validate_config.py
python -m compileall -q .
```

## Shared UI examples

```python
from ui import chart_ui, filter_ui, table_ui, tab_bar, download_button

filter_ui("Lender", "page-lender", lenders, multi=True)
chart_ui(monthly, component_id="page-aum-chart", chart_type="line",
         x="month", y="aum_cr", title="AUM Trend")
table_ui(summary, component_id="page-summary", filterable=True)
tab_bar([("summary", "Summary"), ("detail", "Detail")],
        id_prefix="page-tab-", active="summary")
download_button("page-download", label="Download filtered")
```

Each filter-bearing page places its own `Clear all filters` command beside its
filters. Register the exact dropdown IDs with `register_filter_reset`; the
server-side callback then resets that page deterministically without depending
on browser DOM discovery.

Shared tables preserve the incoming DataFrame column order. Shared pivots use a
configured business sequence from `config/column_order.json` when present and
otherwise preserve the source's first-seen order. Values not yet listed in JSON
are appended after configured values rather than dropped.

Use semantic arguments such as `variant="secondary"` rather than adding inline
style dictionaries. Add a new global option to `ui/components.py` when several
pages genuinely need the same behavior.

All `Last Update` values use the shared `format_timestamp` helper and display
as `YYYY-MM-DD HH-MM`. Pass source timestamps to the helper rather than adding
page-specific `strftime` expressions.

## Styling precedence

When consolidating conflicting legacy styles, use this order:

1. Live Status
2. AUM Dashboard
3. Relationship Tracker

The default header, cards, charts, colours and typography therefore follow Live
Status. AUM conventions supply the default table design. Relationship's blue
table style remains available through `variant="secondary"`.

## IDs

Keep legacy string IDs while editing existing callbacks. New generic components
should use `component_id(page, kind, name)` and log the corresponding
`lineage_id(page, kind, name)`.

```python
from ui import component_id

component_id("aum.portfolio", "visual", "aum_trend")
```

This produces a Dash pattern ID containing the page, component type and name.

### Visible visual identifiers

Every rendered table and chart displays a deterministic identifier in the form
`page.tab.visual`, for example `3.4.12`:

- `page` comes from `dashboards[].serial` in `config/navigation.json`.
- `tab` comes from `subpages.<page>[].serial`; a page without tabs uses `1`.
- `visual` is assigned left-to-right, then top-to-bottom each time the tab is
  rendered.

The same value is attached to the wrapper as `data-visual-id`, and the wrapper
also carries `data-visual-kind="table"` or `"chart"`. This makes screenshots,
support requests and browser inspection point to the same visual. Keep page and
tab serials stable after release; change `order` when only display order should
move.

Each badge also displays the source table code, and its wrapper carries
`data-source-ids`. Source codes are exactly the final six characters of the
Databricks table name. Define a table once in `config/tables.json`, then refer
to only that six-character code in `config/visual_lineage.json`:

```json
"3.1.2": ["gpnbka"]
```

If a visual combines tables, list every source code in calculation/join order.
Never reuse a source code for a different table.

Add the same identifier immediately above the table, chart, or tracked KPI
widget construction in its page module. This is mandatory and checked before
deployment:

```python
# Visual 5.1.1 | table | fvvs4w | Lead Interaction Detail
table_ui(lead_details, component_id="lts-li-table")
```

Tracked KPI widgets show the visual identifier and source suffix inside the
card. Enable this only where the widget participates in lineage by passing
`track_visual=True` to `kpi_card`; untracked KPI cards do not consume a visual
number.

For tables, the visual and source identifiers appear only in the lineage badge
above the table. Column headers remain the original dataset column names, and
downloaded column names use those same names.

All shared tables use one scrollable dataset rather than pagination. Their
bottom summary row remains visible while the body scrolls. `table_ui`
automatically sums numeric columns when the data has no total row; if the page
already supplies a `Total` row, that calculation is preserved and moved to the
bottom. Pass `show_summary=False` only when a table genuinely has no meaningful
summary.

Page serials are currently: Live Status `1`, AUM `2`, Relationship `3`,
Operational Metrics `4`, and LT Sales LMS `5`.

Use a visual scope around any new dynamic tab renderer. Shared `table_ui`,
`matrix_table`, `line_chart`, `multi_line_chart`, and `chart_ui` calls inside
the scope are numbered automatically:

```python
from ui import visual_scope

with visual_scope("relationship", "sales"):
    return build_sales_tables(filtered_data)
```

## Shared data examples

```python
from shared import filter_frame, make_pivot, run_query, unique_values

loans = run_query("SELECT * FROM catalog.schema.loans", context="loans")
filtered = filter_frame(loans, {"lender": selected_lenders})
lenders = unique_values(loans, "lender")
summary = make_pivot(
    filtered,
    rows="product",
    columns="month",
    values="aum",
    aggfunc="sum",
)
```

Do not add a page-specific `get_conn` or `run_query`. Extend `shared/db.py` when
connection behavior must change for every dashboard.
