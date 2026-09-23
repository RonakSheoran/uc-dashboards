"""Reusable pandas transformations with no Dash dependencies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd


DISPLAY_TIMESTAMP_FORMAT = "%Y-%m-%d %H-%M"


def format_timestamp(value: object, fallback: str = "Source timestamp unavailable") -> str:
    """Format dashboard freshness values consistently without changing source data."""
    try:
        timestamp = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return fallback
    if pd.isna(timestamp):
        return fallback
    return timestamp.strftime(DISPLAY_TIMESTAMP_FORMAT)


def unique_values(
    frame: pd.DataFrame | None, column: str, *, stringify: bool = False
) -> list:
    if frame is None or frame.empty or column not in frame.columns:
        return []
    series = frame[column]
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, -1]
    values = [value for value in series.dropna().unique() if str(value).strip()]
    safe_values = []
    for value in values:
        if stringify or isinstance(value, (pd.Timestamp, np.datetime64)):
            safe_values.append(str(value))
        elif isinstance(value, np.generic):
            safe_values.append(value.item())
        else:
            safe_values.append(value)
    return sorted(safe_values, key=lambda value: str(value).casefold())


def normalise_filters(values: Mapping[str, object]) -> dict[str, list]:
    return {
        key: value if isinstance(value, list) else [value]
        for key, value in values.items()
        if value
    }


def filter_frame(
    frame: pd.DataFrame | None,
    filters: Mapping[str, object],
    *,
    stringify: bool = False,
) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame() if frame is None else frame
    output = frame
    for column, selected in filters.items():
        if not selected or column not in output.columns:
            continue
        values = selected if isinstance(selected, list) else [selected]
        if stringify:
            allowed = {str(value) for value in values}
            output = output[output[column].astype(str).isin(allowed)]
        else:
            output = output[output[column].isin(values)]
    return output


def to_numeric(frame: pd.DataFrame, columns: Iterable[str], *, copy: bool = False) -> pd.DataFrame:
    output = frame.copy() if copy else frame
    for column in columns:
        if column in output.columns:
            output[column] = pd.to_numeric(output[column], errors="coerce").fillna(0)
    return output


def make_pivot(
    frame: pd.DataFrame | None,
    *,
    rows: str,
    values: str,
    columns: str | None = None,
    aggfunc: str = "sum",
    fill_value: float = 0,
    column_order: Iterable[object] | None = None,
) -> pd.DataFrame:
    """Create a plain pivot DataFrame for a page to render as needed."""
    required = [rows, values] + ([columns] if columns else [])
    if frame is None or frame.empty or any(column not in frame.columns for column in required):
        return pd.DataFrame()
    work = frame.copy()
    observed_columns = (
        list(dict.fromkeys(work[columns].dropna().tolist())) if columns else []
    )
    if aggfunc != "count":
        work[values] = pd.to_numeric(work[values], errors="coerce").fillna(0)
    pivot = pd.pivot_table(
        work,
        index=rows,
        columns=columns,
        values=values,
        aggfunc=aggfunc,
        fill_value=fill_value,
        sort=False,
    )
    if columns:
        configured = list(column_order or [])
        ordered = [value for value in configured if value in pivot.columns]
        ordered.extend(
            value for value in observed_columns
            if value in pivot.columns and value not in ordered
        )
        pivot = pivot.reindex(columns=ordered)
        pivot.columns = [str(column) for column in pivot.columns]
    return pivot.reset_index()


def make_financial_pivot(
    frame: pd.DataFrame,
    rows_col: str,
    cols_col: str,
    val_col: str,
    agg: str = "sum",
    fmt: str = "{:.2f}",
    divide: float = 1,
    pct: bool = False,
    pct_denom: str | None = None,
) -> pd.DataFrame:
    """Create the formatted, newest-first pivot used by financial pages."""
    required = [rows_col, cols_col, val_col] + ([pct_denom] if pct_denom else [])
    if frame is None or frame.empty or any(column not in frame.columns for column in required):
        return pd.DataFrame()
    work = to_numeric(frame.copy(), [val_col] + ([pct_denom] if pct_denom else []))
    if pct and pct_denom:
        grouped = work.groupby([rows_col, cols_col]).agg(
            {val_col: "sum", pct_denom: "sum"}
        ).reset_index()
        grouped["_value"] = np.where(
            grouped[pct_denom] != 0,
            grouped[val_col] / grouped[pct_denom] * 100,
            0,
        )
    else:
        grouped = work.groupby([rows_col, cols_col]).agg({val_col: agg}).reset_index()
        grouped["_value"] = grouped[val_col] / divide
    pivot = grouped.pivot_table(
        index=rows_col, columns=cols_col, values="_value", aggfunc="sum"
    ).fillna(0)
    try:
        dates = pd.to_datetime(pivot.columns, format="%b-%y")
        pivot = pivot[pivot.columns[dates.argsort()[::-1]]]
    except (TypeError, ValueError):
        pass
    try:
        pivot = pivot.sort_index()
    except TypeError:
        pass
    if pct and pct_denom:
        totals = work.groupby(cols_col).agg({val_col: "sum", pct_denom: "sum"}).reset_index()
        totals["_value"] = np.where(
            totals[pct_denom] != 0,
            totals[val_col] / totals[pct_denom] * 100,
            0,
        )
        for column in pivot.columns:
            match = totals[totals[cols_col] == column]
            pivot.loc["Total", column] = match["_value"].iloc[0] if not match.empty else 0
    else:
        pivot.loc["Total"] = pivot.sum()
    pivot = pivot.reset_index()
    for column in pivot.columns[1:]:
        pivot[column] = pivot[column].map(lambda value: fmt.format(value) if value != 0 else "")
    return pivot
