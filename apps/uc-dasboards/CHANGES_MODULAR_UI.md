# Modular UI refactor

## Full filtered exports

- Truncated detail tables retain their small browser previews and now provide a
  separate **Export all filtered rows** CSV action backed by the complete
  page-filtered DataFrame.
- The built-in table export is disabled on truncated previews so it cannot
  silently produce an incomplete file.
- Coverage includes LT Sales lead and breach details, AUM Max Exact DPD,
  Operational Metrics lead/application/rejection details, Portfolio Monitoring
  details, and Relationship Tracker raw/visit details.

## Mobile layout

- Added a mobile-only layout at 768px and below; desktop presentation remains unchanged.
- Replaced page-level horizontal tabs with dropdown navigation on mobile for AUM,
  Relationship, Operational Metrics, and LT Sales.
- Stacked charts and tables vertically at full available width and retained both-axis
  scrolling for wide or long tables.
- Reduced the collapsed mobile sidebar from 56px to 42px while retaining the existing
  desktop sidebar dimensions.

## Summary-row sorting

- Replaced native sorting on summarized tables with shared custom sorting.
- Sorts only detail rows and always reattaches the Total row at the bottom, preserving
  the sticky summary behaviour on table `2.7.1` and every other summarized table.

## LT Sales LMS

- Added the updated three-tab LT Sales app as page 5: Lead Interaction Summary,
  Anchor Level Summary, and Daily Performance.
- Consolidated shared SQL access, filter controls, clear/refresh behavior,
  scrolling tables, sticky summaries, timestamps, and visual lineage into the
  existing application architecture.
- The interaction and breach detail tables show at most 500 rows in the browser
  while preserving the uploaded app's full cached dataset for filters and summaries.
- Registered visual IDs `5.1.1`, `5.2.1`, `5.3.1`, and `5.3.2` with their exact
  lowercase source suffixes.
- Removed LT Sales manual refresh buttons. Its cached datasets now refresh only
  when the application starts or is redeployed.
- Prevented filter callbacks from rebuilding each table immediately after a tab
  is mounted, reducing duplicate work during tab switching.

## Added

- `ui/components.py`: shared tables, matrices, filters, tabs, headers, cards,
  KPI cards, download buttons and line/bar/area chart factories.
- `ui/config.py`: one cached loader for application JSON and CSS theme tokens.
- `ui/ids.py`: structured component IDs and readable lineage IDs.
- `config/theme.json`: global colours, typography, spacing, cards, charts,
  tables and button defaults.
- `config/navigation.json`: sidebar dashboards and all AUM, Relationship and
  Operational subpage names/order.
- `config/refresh.json`: the Quartz schedule and execution policy.
- `config/app.json`: title, default dashboard and application-level settings.
- `assets/theme.css`: shared responsive styling.
- `tools/validate_config.py`: configuration checks that do not connect to
  Databricks.
- `MAINTAINING.md`: concise editing guide and examples.

## Migrated

- Live Status uses the shared header, KPI, chart and visual-card functions.
- AUM uses shared headers, filters, matrices, detailed tables, charts, states
  and JSON-defined subpage navigation.
- Relationship uses shared headers, red filters, tabs, tables, downloads and error
  states. Its sprint distinctions use coordinated red shades.
- Operational Metrics uses shared headers, KPIs, filters, tables, tabs, states
  and chart theming.
- The shell navigation is generated from JSON instead of a hard-coded list and
  `if/elif` chain.
- `app.yaml` uses the App's `sql-warehouse` resource through `valueFrom` and
  starts the Dash WSGI server with Gunicorn.

## Compatibility

Existing callback IDs and business calculations were intentionally retained.
This allows the new UI outputs to be compared against the existing dashboard
without simultaneously changing financial logic.

## Fixes after initial deployment

- Optional component IDs are now omitted when unset. Dash rejects an explicitly
  supplied `id=None`, which previously prevented headers, KPI cards, tables and
  charts from rendering on affected pages.
- The Databricks listening port is now resolved by `run.py` and passed to
  Gunicorn as a concrete value. Databricks does not run `app.yaml` commands
  through a shell, so `${DATABRICKS_APP_PORT}` was previously passed literally.

## Shared data and visual lineage

- `shared/db.py` now owns SQL authentication, connections, single and batched
  query execution, and TTL caching.
- `shared/frames.py` now owns common filtering, unique-value, numeric and pivot
  transformations.
- Page-specific `get_conn` and `run_query` implementations were removed.
- Every table and chart is visibly labelled `page.tab.visual` and exposes the
  same value as `data-visual-id` for inspection and lineage references.
- Page and tab serials are explicit and validated in `config/navigation.json`.
- `config/tables.json` registers source tables by their unique six-character
  suffix, while `config/visual_lineage.json` maps visual IDs to those suffixes.
- Visual badges and DOM metadata now expose the configured table suffixes.
- Table identifiers are shown only in the lineage badge above each table;
  first-column headers retain their original dataset names.
- Restored an 8 px vertical gutter between the Live Status KPI rows.
- Source table identifiers preserve their exact case in visible lineage badges.
- Live Status KPI widgets now show their visual IDs and lowercase source-table
  suffixes inside each card; the two Live Status charts follow them as visuals
  `1.1.10` and `1.1.11`.
- Reduced identifier and source text to 7 px on Live Status only so lineage
  remains available without distracting from an always-on operational display.
- Removed table pagination globally: every table now exposes its full dataset
  through vertical scrolling.
- Added a sticky bottom summary row to every shared table. Existing page-level
  totals are retained; otherwise numeric columns are summed automatically.
- Replaced the global sidebar reset with page-local `Clear all filters` buttons
  and explicit server-side dropdown resets for every filter-bearing AUM,
  Relationship, Operations and LT Sales pages.
- Standardized every visible `Last Update` value as `YYYY-MM-DD HH-MM` through
  one shared timestamp formatter.
- Added `config/column_order.json` for meaningful pivot-column sequences.
  Tables retain incoming column order, and unconfigured pivot values keep their
  first-seen order rather than being alphabetically rearranged.
