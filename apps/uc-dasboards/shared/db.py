"""Databricks SQL access shared across dashboard modules."""

from __future__ import annotations

import os
import sys
import time
import traceback
from collections.abc import Mapping
from typing import Any

import pandas as pd
from databricks import sql as dbsql
from databricks.sdk.core import Config


DEFAULT_WAREHOUSE_ID = "e6b3b3d8399e5edb"
_config = Config()


def get_connection(warehouse_id: str | None = None):
    """Create a SQL connection using the Databricks App service principal."""
    resolved_warehouse = warehouse_id or os.getenv(
        "DATABRICKS_WAREHOUSE_ID", DEFAULT_WAREHOUSE_ID
    )
    return dbsql.connect(
        server_hostname=_config.host,
        http_path=f"/sql/1.0/warehouses/{resolved_warehouse}",
        credentials_provider=lambda: _config.authenticate,
    )


def _rows_to_frame(cursor) -> pd.DataFrame:
    columns = [description[0] for description in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def run_query(
    query: str,
    *,
    warehouse_id: str | None = None,
    context: str = "query",
    raise_on_error: bool = False,
) -> pd.DataFrame:
    """Execute one query and return an empty frame on failure by default."""
    try:
        with get_connection(warehouse_id) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query)
                result = _rows_to_frame(cursor)
        print(f"[{context}] {len(result)} rows", file=sys.stderr)
        return result
    except Exception as exc:
        print(f"[{context}] failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        if raise_on_error:
            raise
        return pd.DataFrame()


def run_queries(
    queries: Mapping[str, str],
    *,
    warehouse_id: str | None = None,
    context: str = "query batch",
    raise_on_error: bool = False,
) -> dict[str, pd.DataFrame]:
    """Run a named query batch on one connection to avoid repeated handshakes."""
    results: dict[str, pd.DataFrame] = {}
    try:
        with get_connection(warehouse_id) as connection:
            for name, query in queries.items():
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(query)
                        results[name] = _rows_to_frame(cursor)
                    print(f"[{context}:{name}] {len(results[name])} rows", file=sys.stderr)
                except Exception as exc:
                    print(f"[{context}:{name}] failed: {exc}", file=sys.stderr)
                    if raise_on_error:
                        raise
                    results[name] = pd.DataFrame()
        return results
    except Exception:
        if raise_on_error:
            raise
        traceback.print_exc(file=sys.stderr)
        return {name: results.get(name, pd.DataFrame()) for name in queries}


class QueryCache:
    """Small in-process TTL cache for query/table results."""

    def __init__(self, ttl_seconds: int = 1800):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, dict[str, Any]] = {}

    def get(self, key: str, loader, *, copy: bool = False) -> pd.DataFrame:
        now = time.time()
        cached = self._items.get(key)
        if cached and now - float(cached["timestamp"]) < self.ttl_seconds:
            frame = cached["frame"]
        else:
            frame = loader()
            self._items[key] = {"timestamp": now, "frame": frame}
        return frame.copy() if copy else frame

    def put(self, key: str, frame: pd.DataFrame) -> None:
        """Store a preloaded frame, used for atomic whole-app refreshes."""
        self._items[key] = {"timestamp": time.time(), "frame": frame}

    def clear(self, key: str | None = None) -> None:
        if key is None:
            self._items.clear()
        else:
            self._items.pop(key, None)
