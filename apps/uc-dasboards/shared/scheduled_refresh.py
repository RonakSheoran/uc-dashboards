"""Process-wide scheduled refresh for every dashboard data snapshot."""

from __future__ import annotations

import atexit
import sys
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


RefreshHook = Callable[[], object]

_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_REVISION = 0


def _schedule(refresh_config: Mapping) -> tuple[ZoneInfo, tuple]:
    timezone = ZoneInfo(refresh_config.get("timezone", "Asia/Kolkata"))
    policy_name = refresh_config.get("app_policy")
    policy = refresh_config.get("policies", {}).get(policy_name, {})
    values = policy.get("times", [])
    times = tuple(sorted(datetime.strptime(value, "%H:%M").time() for value in values))
    return timezone, times


def _next_run(now: datetime, times: tuple) -> datetime:
    for wall_time in times:
        candidate = datetime.combine(now.date(), wall_time, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    return datetime.combine(now.date() + timedelta(days=1), times[0], tzinfo=now.tzinfo)


def refresh_all_data(hooks: Mapping[str, RefreshHook], *, reason: str) -> dict[str, bool]:
    """Run every refresh hook; one failed page never blocks the remaining pages."""
    global _REVISION
    if not _LOCK.acquire(blocking=False):
        print(f"[APP REFRESH] Skipped overlapping {reason} refresh", file=sys.stderr)
        return {}

    results: dict[str, bool] = {}
    try:
        print(f"[APP REFRESH] Starting {reason} refresh", file=sys.stderr)
        for name, hook in hooks.items():
            try:
                results[name] = hook() is not False
            except Exception as exc:
                results[name] = False
                print(f"[APP REFRESH] {name} failed: {exc}", file=sys.stderr)
        _REVISION += 1
        print(f"[APP REFRESH] Completed {reason} refresh: {results}", file=sys.stderr)
        return results
    finally:
        _LOCK.release()


def current_refresh_revision() -> int:
    return _REVISION


def _scheduler_loop(refresh_config: Mapping, hooks: Mapping[str, RefreshHook]) -> None:
    timezone, times = _schedule(refresh_config)
    if not times:
        print("[APP REFRESH] No scheduled refresh times configured", file=sys.stderr)
        return

    while not _STOP.is_set():
        now = datetime.now(timezone)
        target = _next_run(now, times)
        wait_seconds = max((target - now).total_seconds(), 0)
        print(f"[APP REFRESH] Next full refresh: {target.isoformat()}", file=sys.stderr)
        if _STOP.wait(wait_seconds):
            return
        refresh_all_data(hooks, reason="scheduled")


def start_global_refresh_scheduler(
    refresh_config: Mapping,
    hooks: Mapping[str, RefreshHook],
) -> None:
    """Start one daemon scheduler after every dashboard module is imported."""
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(
        target=_scheduler_loop,
        args=(refresh_config, dict(hooks)),
        name="dashboard-global-refresh",
        daemon=True,
    )
    _THREAD.start()


@atexit.register
def _stop_scheduler() -> None:
    _STOP.set()
