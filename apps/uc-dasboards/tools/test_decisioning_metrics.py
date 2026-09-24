import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decisioning_metrics import apply_filters, month_dates, prepare, summarize


raw = pd.DataFrame({
    "application_id": ["A", "B", "C", "D", "E", "F", "A"],
    "application_purpose": ["WORKING_CAPITAL", "WORKING_CAPITAL", "WORKING_CAPITAL", "WORKING_CAPITAL", "WORKING_CAPITAL", "OTHER", "WORKING_CAPITAL"],
    "incorporation_type": ["PROPRIETORSHIP", "PROPRIETORSHIP", "PRIVATE_LIMITED", "PROPRIETORSHIP", "PROPRIETORSHIP", "PROPRIETORSHIP", "PROPRIETORSHIP"],
    "uw_poc": ["UW1", "UW1", "UW2", "UW2", "UW1", "UW1", "UW1"],
    "new_limit": [1000000, 1000000, 2000000, 6000000, 1000000, 1000000, 1000000],
    "higher_approval_poc": ["HA1", "HA1", "HA2", "HA2", "HA1", "HA1", "HA1"],
    "application_created_date": ["2026-09-19"] * 7,
    "tat_minutes": [30, 80, 20, 40, 50, "bad", 70],
    "decision_at": ["2026-09-20 10:00"] * 6 + ["2026-09-20 11:00"],
    "high_ticket_flag": [0, 0, 0, 1, 0, 0, 0],
    "deviation_flag": [0, 0, 0, 0, 1, 0, 0],
})
frame = prepare(raw)
result = summarize(frame)
assert result["total"] == 6
assert result["stages"] == [1, 1, 1]
assert result["eligible"] == 3
assert result["under_60"] == 1
assert result["total_tat"] == 68
assert result["stage_tats"] == [40, 50, 20]
assert result["eligible_tat"] == 75
assert result["balance"] == 3
assert result["balance_tat"] == 48
assert result["eligible_pct"] == 50
assert result["balance_pct"] == 50
assert result["eligible"] + result["balance"] == result["total"]
assert abs(result["rate_pct"] - (100 / 3)) < 1e-8
assert str(frame["_date"].iloc[0]) == "2026-09-19"
assert summarize(apply_filters(frame, uw_poc=["UW2"]))["stages"] == [1, 0, 1]
assert summarize(apply_filters(frame, new_limit=[2000000]))["eligible"] == 0
assert summarize(apply_filters(frame, higher_approval_poc=["HA1"], application_id=["A"]))["under_60"] == 1
assert result["eligible"] == result["total"] - sum(result["stages"])
assert summarize(apply_filters(frame, application_purpose=["OTHER"]))["eligible"] == 1
assert len(month_dates("2026-09", "2026-09-23")) == 23
assert str(month_dates("2026-09", "2026-09-23")[-1]) == "2026-09-23"
assert len(month_dates("2026-08", "2026-09-23")) == 31
assert len(month_dates("2026-10", "2026-09-23")) == 0
print("PASS: incorporation-based eligibility, five filters, creation date, distinct counts and 60-minute SLA")
