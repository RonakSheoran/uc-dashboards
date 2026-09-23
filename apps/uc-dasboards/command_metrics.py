"""Pure transformations for the invoice command-center pages."""
import pandas as pd

UNITS = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}


def prepare(frame, config):
    frame = frame.copy()
    tat_column = config["tat_column"]
    if tat_column in frame:
        frame[tat_column] = pd.to_numeric(frame[tat_column], errors="coerce")
    for rule in config.get("row_filters", []):
        mask = rule_mask(frame, rule)
        if mask is None:
            raise KeyError(f"Cannot apply configured row filter: {rule}")
        frame = frame[mask]
    # Date cohort is the source's date portion; no unconfirmed timezone conversion.
    frame["_date"] = pd.to_datetime(frame[config["date_column"]].astype(str).str[:10], errors="coerce").dt.date
    return frame


def rule_mask(frame, rule):
    col = rule.get("column")
    if not col or col not in frame:
        return None
    if rule["op"] == "in" and rule.get("values") is not None:
        return frame[col].isin(rule["values"])
    if rule["op"] == "eq" and rule.get("value") is not None:
        if isinstance(rule["value"], (int, float)):
            return pd.to_numeric(frame[col], errors="coerce").eq(rule["value"])
        return frame[col].astype("string").str.strip().str.upper().eq(str(rule["value"]).strip().upper())
    if rule["op"] == "gte" and rule.get("value") is not None:
        return pd.to_numeric(frame[col], errors="coerce").ge(rule["value"])
    values = pd.to_numeric(frame[col], errors="coerce")
    if rule["op"] == "lte" and rule.get("value") is not None:
        return values.le(rule["value"])
    if rule["op"] == "gt" and rule.get("value") is not None:
        return values.gt(rule["value"])
    if rule["op"] == "between_gt_lte" and rule.get("lower") is not None and rule.get("upper") is not None:
        return values.gt(rule["lower"]) & values.le(rule["upper"])
    return None


def seconds(frame, column, unit):
    if column not in frame or unit not in UNITS:
        return None
    return pd.to_numeric(frame[column], errors="coerce") * UNITS[unit]


def summarize(frame, config):
    id_column = config["id_column"]
    count = int(frame[id_column].nunique()) if id_column in frame else 0
    source_tat = pd.to_numeric(frame.get(config.get("tat_column")), errors="coerce")
    tat = seconds(frame, config.get("tat_column"), config.get("tat_unit"))
    masks = [rule_mask(frame, r) for r in config["exclusions"]]
    remaining = pd.Series(True, index=frame.index)
    stages = []
    stage_tats = []
    known = True
    def percentile(series):
        return float(series.quantile(.9)) if series is not None and series.notna().any() else None
    for mask in masks:
        if mask is None:
            known = False
            stages.append(None)
            stage_tats.append(None)
        else:
            cohort = remaining & mask
            stages.append(int(frame.loc[cohort, id_column].nunique()))
            stage_tats.append(percentile(tat[cohort]))
            remaining &= ~mask
    balance = ~remaining
    return {
        "total": count,
        "rate_pct": 100 * source_tat.lt(config["threshold_value"]).sum() / count if count else None,
        "eligible_pct": 100 * frame.loc[remaining, id_column].nunique() / count if known and count else None,
        "balance_pct": 100 * frame.loc[balance, id_column].nunique() / count if known and count else None,
        "eligible_tat": percentile(tat[remaining]) if known and tat is not None else None,
        "balance_tat": percentile(tat[balance]) if known and tat is not None else None,
        "overall": float(seconds(frame, config.get("overall_column"), config.get("overall_unit")).mean()) if count else None,
        "total_tat": percentile(tat),
        "eligible": int(frame.loc[remaining, id_column].nunique()) if known else None,
        "stages": stages,
        "stage_tats": stage_tats,
    }
