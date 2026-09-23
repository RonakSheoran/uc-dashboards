# Command centers

The 300s Command Center has Eligibility Snapshot and Waterfall Funnel tabs and
reuses the shared red theme, mobile tab dropdown, scrollable exportable tables,
loading overlay and navigation tracking. The 60-minute page has been removed.

The page is configured in config/command_centers.json and uses
hive_metastore.probes.tat_fix_gnhgks. invoice_tat is read directly in seconds.
Counts are distinct invoice IDs grouped by latest_invoice_timestamp for seven
completed IST calendar days.
The page-level Last Update badge uses the source's refresh_time column.

The source table is already filtered to the required disbursal population. The under-five-minute
metric uses invoice_tat < 300. Eligibility exclusions are applied sequentially:
lender = MFL, then risky_customer = 1 among the remainder, then
invoice_amount_tag = '5L+' among the remainder. Everything left is eligible.
System error is not used.

The snapshot trend table contains Date, Total Invoices, % Disbursed <5 Min,
% Eligible, TAT Eligible, % Balance, TAT Balance and Overall TAT. The waterfall
tab contains two tables with the same columns: positive sequential cohort counts and
P90 invoice_tat for the total, each excluded cohort and net eligible cohort.

Data loads on first visit and uses a process-shared 15-minute cache, polled by
the page interval. A failed refresh preserves the previous successful snapshot.
Percentiles and percentages intentionally have no summed Total footer.

Deploy the full uc-dashboards folder. No new packages are required. Local tests
cover transformations and package registration; live warehouse access has not
been tested in this environment.
