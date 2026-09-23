"""Non-blocking dashboard tab-click telemetry."""

from __future__ import annotations

import atexit
import os
import queue
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import has_request_context, request

from .db import get_connection


EVENT_TABLE = os.getenv(
    "DASHBOARD_EVENTS_TABLE",
    "hive_metastore.credit.uc_dashboard_app_events",
)
_TABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
if not _TABLE_PATTERN.fullmatch(EVENT_TABLE):
    raise ValueError("DASHBOARD_EVENTS_TABLE must be a three-part catalog.schema.table name")

_IST = ZoneInfo("Asia/Kolkata")
_EVENTS: queue.Queue[tuple] = queue.Queue(maxsize=10_000)
_START_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None
_STOP = threading.Event()
_TABLE_READY = False


def _current_user() -> str | None:
    if not has_request_context():
        return None
    return (
        request.headers.get("X-Forwarded-Email")
        or request.headers.get("X-Forwarded-User")
    )


def track_tab_click(dashboard_id: str, tab_id: str) -> None:
    """Queue one authenticated page/tab selection without delaying its callback."""
    user = _current_user()
    if not user:
        return
    now = datetime.now(timezone.utc)
    event = (
        str(uuid.uuid4()),
        now.replace(tzinfo=None),
        now.astimezone(_IST).date(),
        user,
        str(dashboard_id),
        str(tab_id),
    )
    try:
        _EVENTS.put_nowait(event)
    except queue.Full:
        print("[analytics] event queue full; click event dropped", file=sys.stderr)
        return
    _start_worker()


def _start_worker() -> None:
    global _WORKER
    with _START_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _STOP.clear()
            _WORKER = threading.Thread(target=_worker_loop, name="dashboard-analytics", daemon=True)
            _WORKER.start()


def _ensure_table(cursor) -> None:
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {EVENT_TABLE} (
            event_id STRING,
            event_time TIMESTAMP,
            event_date DATE,
            user_email STRING,
            dashboard_id STRING,
            tab_id STRING
        ) USING DELTA
        """
    )


def _write_batch(rows: list[tuple]) -> None:
    global _TABLE_READY
    with get_connection() as connection:
        with connection.cursor() as cursor:
            if not _TABLE_READY:
                _ensure_table(cursor)
                _TABLE_READY = True
            cursor.executemany(
                f"""
                INSERT INTO {EVENT_TABLE}
                    (event_id, event_time, event_date, user_email, dashboard_id, tab_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )


def _worker_loop() -> None:
    while not _STOP.is_set():
        try:
            first = _EVENTS.get(timeout=5)
        except queue.Empty:
            continue
        batch = [first]
        # Briefly collect concurrent clicks into one warehouse write.
        _STOP.wait(1)
        while len(batch) < 100:
            try:
                batch.append(_EVENTS.get_nowait())
            except queue.Empty:
                break
        try:
            _write_batch(batch)
        except Exception as exc:
            # Telemetry must never break dashboard navigation.
            print(f"[analytics] click batch failed: {exc}", file=sys.stderr)
        finally:
            for _ in batch:
                _EVENTS.task_done()


@atexit.register
def _stop_worker() -> None:
    _STOP.set()
