"""Daily-source observability channel.

Mirrors benz pattern: writes one row per parser-run to a `daily_source_log`
table — separate from the domain model. Schema:

    (source, rows_added, rows_updated, http_status, error, duration_ms)

NO `raw` column by design (benz durable rule #18). Diagnostics are packed
into `error` as a '|' separator between key=value pairs.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class SupportsExecute(Protocol):
    """Minimal DB-API connection interface (psycopg3 compatible)."""

    def execute(self, sql: str, params: tuple | None = None) -> Any: ...
    def commit(self) -> None: ...


class DailySourceLog:
    """Writer for daily_source_log. Pass an open DB connection per call.

    Pattern (benz):
        with get_conn() as conn:
            DailySourceLog(conn).write(
                source='minfin_detail',
                rows_added=inserts,
                rows_updated=updates,
                http_status=200,
                error=None,           # or 'no_rows_parsed' or 'HTTP 503'
                duration_ms=duration,
            )
    """

    def __init__(self, conn: SupportsExecute) -> None:
        self.conn = conn

    def write(
        self,
        *,
        source: str,
        rows_added: int,
        rows_updated: int,
        http_status: int | None,
        error: str | None,
        duration_ms: int,
    ) -> None:
        """Insert one row. Caller is responsible for transaction commit.

        Note: psycopg3.Connection supports `conn.execute(sql, params)` directly,
        which internally uses a cursor. So we use that — matches both real
        psycopg3 Connection objects and our mock that exposes `.execute()`.
        """
        self.conn.execute(
            """
            INSERT INTO daily_source_log
                (source, rows_added, rows_updated, http_status, error, duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (source, rows_added, rows_updated, http_status, error, duration_ms),
        )

    def write_diag(
        self,
        *,
        source: str,
        rows_added: int,
        rows_updated: int,
        http_status: int | None,
        duration_ms: int,
        diag: dict[str, int | str],
        error_prefix: str | None = None,
    ) -> None:
        """Write a row with `diag` packed into the error column.

        Diagnostic format follows the benz loader pattern:
            "channels_ok=10|channels_empty=2|channels_err=0|duration_s=12"
        """
        diag_str = "|".join(f"{k}={v}" for k, v in diag.items())
        error = f"{error_prefix} | {diag_str}" if error_prefix else diag_str
        self.write(
            source=source,
            rows_added=rows_added,
            rows_updated=rows_updated,
            http_status=http_status,
            error=error,
            duration_ms=duration_ms,
        )


__all__ = ["DailySourceLog", "SupportsExecute"]
