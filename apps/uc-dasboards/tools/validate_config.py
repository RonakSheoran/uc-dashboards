"""Validate dashboard JSON without starting Dash or querying Databricks."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def read(name: str) -> dict:
    path = CONFIG / name
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level value must be an object")
    return value


def unique_ids(items: list[dict], location: str) -> set[str]:
    ids = [item.get("id") for item in items]
    missing = [index for index, value in enumerate(ids) if not value]
    if missing:
        raise ValueError(f"{location}: missing id at indexes {missing}")
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"{location}: duplicate ids: {duplicates}")
    return set(ids)


def unique_serials(items: list[dict], location: str) -> None:
    serials = [item.get("serial") for item in items]
    invalid = [
        index for index, value in enumerate(serials)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1
    ]
    if invalid:
        raise ValueError(f"{location}: invalid or missing serial at indexes {invalid}")
    duplicates = sorted({value for value in serials if serials.count(value) > 1})
    if duplicates:
        raise ValueError(f"{location}: duplicate serials: {duplicates}")


def validate() -> None:
    app = read("app.json")
    navigation = read("navigation.json")
    refresh = read("refresh.json")
    table_config = read("tables.json")
    theme = read("theme.json")
    lineage_config = read("visual_lineage.json")
    column_order_config = read("column_order.json")

    dashboards = navigation.get("dashboards", [])
    dashboard_ids = unique_ids(dashboards, "navigation.dashboards")
    unique_serials(dashboards, "navigation.dashboards")
    if app.get("default_dashboard") not in dashboard_ids:
        raise ValueError("app.default_dashboard does not exist in navigation.dashboards")

    for group, pages in navigation.get("subpages", {}).items():
        if group not in dashboard_ids:
            raise ValueError(f"navigation.subpages.{group}: unknown dashboard")
        unique_ids(pages, f"navigation.subpages.{group}")
        unique_serials(pages, f"navigation.subpages.{group}")

    tables = table_config.get("tables", {})
    if not isinstance(tables, dict) or not tables:
        raise ValueError("tables.json.tables must be a non-empty object")
    full_names = []
    for source_id, source in tables.items():
        if not re.fullmatch(r"[A-Za-z0-9]{6}", source_id):
            raise ValueError(f"tables.json: source id must contain six characters: {source_id}")
        table_name = source.get("table", "") if isinstance(source, dict) else ""
        if not table_name.endswith(source_id):
            raise ValueError(f"tables.json.{source_id}: table must end with its source id")
        full_names.append(f"{source.get('schema', '')}.{table_name}")
    if len(full_names) != len(set(full_names)):
        raise ValueError("tables.json: duplicate fully qualified table names")

    column_orders = column_order_config.get("columns", {})
    if not isinstance(column_orders, dict):
        raise ValueError("column_order.json.columns must be an object")
    for column, values in column_orders.items():
        if not isinstance(column, str) or not column:
            raise ValueError("column_order.json: column names must be non-empty strings")
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f"column_order.json.{column}: order must be a list of strings")
        if len(values) != len(set(values)):
            raise ValueError(f"column_order.json.{column}: duplicate ordered values")

    page_tabs = {}
    for dashboard in dashboards:
        page_serial = int(dashboard["serial"])
        tabs = navigation.get("subpages", {}).get(dashboard["id"], [])
        page_tabs[page_serial] = {int(tab["serial"]) for tab in tabs} or {1}
    visuals = lineage_config.get("visuals", {})
    if not isinstance(visuals, dict):
        raise ValueError("visual_lineage.json.visuals must be an object")
    visual_serials: dict[tuple[int, int], list[int]] = {}
    for visual_id, source_ids in visuals.items():
        if not re.fullmatch(r"[1-9]\d*\.[1-9]\d*\.[1-9]\d*", visual_id):
            raise ValueError(f"visual_lineage.json: invalid visual id {visual_id}")
        page_serial, tab_serial, visual_serial = map(int, visual_id.split("."))
        if page_serial not in page_tabs or tab_serial not in page_tabs[page_serial]:
            raise ValueError(f"visual_lineage.json: unknown page/tab in {visual_id}")
        visual_serials.setdefault((page_serial, tab_serial), []).append(visual_serial)
        if not isinstance(source_ids, list) or not source_ids:
            raise ValueError(f"visual_lineage.json.{visual_id}: sources must be a non-empty list")
        unknown = sorted(set(source_ids) - set(tables))
        if unknown:
            raise ValueError(f"visual_lineage.json.{visual_id}: unknown source ids {unknown}")
    for scope, serials in visual_serials.items():
        expected = list(range(1, max(serials) + 1))
        if sorted(serials) != expected:
            raise ValueError(f"visual_lineage.json: non-contiguous visuals for {scope}")

    comment_pattern = re.compile(
        r"# Visual (\d+\.\d+\.\d+) \| (?:table|chart|widget) \| ([A-Za-z0-9]{6}) \|"
    )
    visual_comments: dict[str, str] = {}
    for dashboard in dashboards:
        module_path = ROOT / f"{dashboard['module']}.py"
        if not module_path.exists():
            raise ValueError(f"navigation.dashboards: missing module {module_path.name}")
        for visual_id, source_id in comment_pattern.findall(module_path.read_text(encoding="utf-8")):
            if visual_id in visual_comments:
                raise ValueError(f"duplicate visual comment: {visual_id}")
            visual_comments[visual_id] = source_id
    missing_comments = sorted(set(visuals) - set(visual_comments))
    extra_comments = sorted(set(visual_comments) - set(visuals))
    if missing_comments:
        raise ValueError(f"missing visual comments: {missing_comments}")
    if extra_comments:
        raise ValueError(f"visual comments missing from lineage JSON: {extra_comments}")
    mismatched_comments = sorted(
        visual_id for visual_id, source_id in visual_comments.items()
        if source_id not in visuals[visual_id]
    )
    if mismatched_comments:
        raise ValueError(f"visual comment source mismatch: {mismatched_comments}")

    policies = refresh.get("policies", {})
    app_policy = refresh.get("app_policy")
    if app_policy not in policies:
        raise ValueError(f"refresh.app_policy: unknown policy {app_policy}")
    for dashboard_id, policy_id in refresh.get("dashboard_policy", {}).items():
        if dashboard_id not in dashboard_ids:
            raise ValueError(f"refresh.dashboard_policy: unknown dashboard {dashboard_id}")
        if policy_id not in policies:
            raise ValueError(f"refresh.dashboard_policy.{dashboard_id}: unknown policy {policy_id}")
    for policy_id, policy in policies.items():
        expression = policy.get("quartz_cron")
        times = policy.get("times")
        if expression is not None:
            if len(expression.split()) != 7:
                raise ValueError(f"refresh.policies.{policy_id}.quartz_cron must have 7 Quartz fields")
        elif times is not None:
            if not isinstance(times, list) or not times:
                raise ValueError(f"refresh.policies.{policy_id}.times must be a non-empty list")
            invalid_times = []
            for value in times:
                match = re.fullmatch(r"(\d{2}):(\d{2})", value) if isinstance(value, str) else None
                if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
                    invalid_times.append(value)
            if invalid_times:
                raise ValueError(
                    f"refresh.policies.{policy_id}.times contains invalid HH:MM values: {invalid_times}"
                )
            if len(times) != len(set(times)):
                raise ValueError(f"refresh.policies.{policy_id}.times contains duplicates")
        else:
            raise ValueError(
                f"refresh.policies.{policy_id} must define quartz_cron or times"
            )

    required_theme_sections = {"colors", "typography", "cards", "charts", "tables", "buttons"}
    missing_sections = sorted(required_theme_sections - set(theme))
    if missing_sections:
        raise ValueError(f"theme.json: missing sections {missing_sections}")


if __name__ == "__main__":
    try:
        validate()
    except ValueError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("Configuration is valid")
