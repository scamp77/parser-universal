"""DB helpers — psycopg3 connection factory + transaction context.

Pattern derived from benz `app.core.db.get_conn` and sup-app `db.py`.

Usage:
    from parser_universal.db import get_conn, transaction

    with transaction() as conn:
        sink = PostgresSink(conn, table='gas_station_prices', soft_delete_col='removed_at')
        result = await sink.upsert(entity)
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

__all__ = ["get_conn", "transaction"]


def get_conn() -> Any:
    """Open a psycopg3 connection from POSTGRES_DSN or DATABASE_URL env.

    Prefers POSTGRES_DSN (benz convention); falls back to DATABASE_URL.
    """
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg3 is required for the DB layer: `pip install 'psycopg[binary]>=3.2'`"
        ) from exc
    dsn = os.environ.get("POSTGRES_DSN") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError(
            "set POSTGRES_DSN (or DATABASE_URL) environment variable"
        )
    return psycopg.connect(dsn, autocommit=False)


@contextmanager
def transaction():
    """Context manager: yields a psycopg3 conn, commits on success, rollback on exc."""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
