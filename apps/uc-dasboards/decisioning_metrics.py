"""Pure transformations for the 60-minute decisioning command center."""
from __future__ import annotations

import pandas as pd


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize the probe output without changing the source business fields."""
    required = {
        "application_id", "application_purpose", "uw_poc", "new_limit",
        "higher_approval_poc", "application_created_date", "incorporation_type",
        "tat_minutes", "decision_at",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"60-minute probe is missing required columns: {', '.join(missing)}")
    result = frame.copy()
    result["application_id"] = result["application_id"].astype("string")
    result["application_purpose"] = result["application_purpose"].astype("string")
    result["uw_poc"] = result["uw_poc"].astype("string")
    result["higher_approval_poc"] = result["higher_approval_poc"].astype("string")
    result["incorporation_type"] = result["incorporation_type"].astype("string")
    result["new_limit"] = pd.to_numeric(result["new_limit"], errors="coerce")
    result["tat_minutes"] = pd.to_numeric(result["tat_minutes"], errors="coerce")
    result["decision_at"] = pd.to_datetime(result["decision_at"], errors="coerce")
    result["_date"] = pd.to_datetime(result["application_created_date"], errors="coerce").dt.date
    for column in ("high_ticket_flag", "deviation_flag"):
        result[column] = pd.to_numeric(result.get(column), errors="coerce").fillna(0).astype(int)
    return result[result["application_id"].notna() & result["_date"].notna()]


def apply_filters(frame, application_purpose=None, uw_poc=None, application_id=None,
                  new_limit=None, higher_approval_poc=None):
    result = frame
    for column, selected in (
        ("application_purpose", application_purpose),
        ("uw_poc", uw_poc),
        ("application_id", application_id),
        ("new_limit", new_limit),
        ("higher_approval_poc", higher_approval_poc),
    ):
        if selected:
            values = selected if isinstance(selected, list) else [selected]
            result = result[result[column].isin(values)]
    return result


def month_dates(month, today):
    """Return each calendar day in a month, stopping at today for the current month."""
    start = pd.Period(month, freq="M").start_time
    end = pd.Period(month, freq="M").end_time.normalize()
    today = pd.Timestamp(today).normalize()
    if start > today:
        return []
    return pd.date_range(start, min(end, today), freq="D").date


def _p90(series):
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.quantile(.9)) if not values.empty else None


def summarize(frame: pd.DataFrame, proprietorship_value="PROPRIETORSHIP", threshold=60):
    """Apply the waterfall sequentially and return distinct-application metrics."""
    frame = frame.sort_values("decision_at").drop_duplicates("application_id", keep="first").copy()
    remaining = pd.Series(True, index=frame.index)
    incorporation_type = frame["incorporation_type"].fillna("").str.strip().str.upper()
    rules = [
        frame["high_ticket_flag"].eq(1),
        frame["deviation_flag"].eq(1),
        incorporation_type.ne(str(proprietorship_value).strip().upper()),
    ]
    stages = []
    stage_tats = []
    for rule in rules:
        cohort = remaining & rule
        stages.append(int(frame.loc[cohort, "application_id"].nunique()))
        stage_tats.append(_p90(frame.loc[cohort, "tat_minutes"]))
        remaining &= ~rule

    eligible = frame.loc[remaining]
    balance = frame.loc[~remaining]
    eligible_count = int(eligible["application_id"].nunique())
    balance_count = int(balance["application_id"].nunique())
    under = eligible[eligible["tat_minutes"].lt(threshold)]
    under_count = int(under["application_id"].nunique())
    total = int(frame["application_id"].nunique())
    return {
        "total": total,
        "total_tat": _p90(frame["tat_minutes"]),
        "stages": stages,
        "stage_tats": stage_tats,
        "eligible": eligible_count,
        "eligible_pct": 100 * eligible_count / total if total else None,
        "eligible_tat": _p90(eligible["tat_minutes"]),
        "balance": balance_count,
        "balance_pct": 100 * balance_count / total if total else None,
        "balance_tat": _p90(balance["tat_minutes"]),
        "under_60": under_count,
        "over_60": max(eligible_count - under_count, 0),
        "rate_pct": 100 * under_count / eligible_count if eligible_count else None,
    }


def breakdown(frame: pd.DataFrame, proprietorship_value="PROPRIETORSHIP", threshold=60):
    rows = []
    for purpose, group in frame.groupby("application_purpose", dropna=False):
        metrics = summarize(group, proprietorship_value, threshold)
        rows.append({"Application Purpose": str(purpose), **metrics})
    return rows
