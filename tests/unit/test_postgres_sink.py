"""Unit tests for PostgresSink — uses a mock cursor/connection.

We do NOT spin up a real Postgres (no testcontainers in Phase 2 unit scope).
The mock verifies SQL composition: ON CONFLICT clause, JSONB || merge,
soft-delete re-activation (removed_at = NULL).
"""

from __future__ import annotations

from parser_universal.sinks.postgres import PostgresSink
from parser_universal.types import DomainEntity


class MockCursor:
    """Records execute() calls and returns a configurable row on fetchone()."""

    def __init__(self, return_row: tuple | None = (True,)):
        self.executed: list[tuple[str, tuple]] = []
        self._row = return_row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._row

    def commit(self):
        pass

    def rollback(self):
        pass


class MockConn:
    def __init__(self, return_row: tuple | None = (True,)):
        self._cursor = MockCursor(return_row)
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _entity(**overrides):
    base = dict(
        entity_type="gas_station",
        source="minfin",
        source_id="station-1",
        geom=(50.0, 30.0),
        attrs={"brand": "OKKO", "octane_95": 47.50},
        bbox_country="UA",
        confidence=1.0,
    )
    base.update(overrides)
    return DomainEntity(**base)


def test_upsert_insert_path():
    conn = MockConn(return_row=(True,))  # xmax=0 → INSERTED
    sink = PostgresSink(conn, table="entities")
    import asyncio

    result = asyncio.run(
        sink.upsert(_entity(source_id="ins-test"))
    )
    sql, params = conn._cursor.executed[0]
    sql_flat = " ".join(sql.split())
    assert "INSERT INTO entities" in sql_flat
    assert "ON CONFLICT (source, source_id) DO UPDATE" in sql_flat
    assert "entities.attrs || EXCLUDED.attrs" in sql_flat  # JSONB || merge
    assert "removed_at = NULL" in sql_flat  # soft-delete re-activation
    assert params[0] == "minfin"
    assert params[1] == "ins-test"
    # params[3] is psycopg.types.json.Json wrapper; render its inner value to check.
    geom_payload = (
        params[3].obj if hasattr(params[3], "obj") else params[3]
    )
    assert geom_payload == {"type": "Point", "coordinates": [30.0, 50.0]}
    assert conn.commits == 1
    assert result.value == "inserted"


def test_upsert_update_path():
    conn = MockConn(return_row=(False,))  # xmax!=0 → UPDATED
    sink = PostgresSink(conn, table="entities")
    import asyncio

    result = asyncio.run(
        sink.upsert(_entity(source_id="upd-test"))
    )
    assert result.value == "updated"


def test_upsert_geometry_uses_lon_lat_order():
    """GeoJSON convention: coordinates array is [lon, lat].

    Critical: many parsers confuse this; we test the contract here.
    """
    conn = MockConn(return_row=(True,))
    sink = PostgresSink(conn, table="t")
    import asyncio

    e = _entity(geom=(50.0, 30.0))  # (lat=50, lon=30)
    asyncio.run(sink.upsert(e))
    geom_payload = conn._cursor.executed[0][1][3]
    geom_payload = (
        geom_payload.obj if hasattr(geom_payload, "obj") else geom_payload
    )
    assert geom_payload["coordinates"] == [30.0, 50.0]  # [lon, lat] order


def test_upsert_no_geom():
    conn = MockConn()
    sink = PostgresSink(conn, table="t")
    import asyncio

    asyncio.run(sink.upsert(_entity(geom=None)))
    geom_param = conn._cursor.executed[0][1][3]
    assert geom_param is None


def test_upsert_do_nothing_branch():
    conn = MockConn(return_row=(True,))
    sink = PostgresSink(conn, table="t", on_conflict="DO_NOTHING")
    import asyncio

    asyncio.run(sink.upsert(_entity(source_id="x")))
    sql_flat = " ".join(conn._cursor.executed[0][0].split())
    assert "DO NOTHING" in sql_flat
    assert "DO UPDATE" not in sql_flat


def test_upsert_no_soft_delete_when_disabled():
    conn = MockConn(return_row=(True,))
    sink = PostgresSink(conn, table="t", soft_delete_col=None)
    import asyncio

    asyncio.run(sink.upsert(_entity(source_id="nsd")))
    sql_flat = " ".join(conn._cursor.executed[0][0].split())
    assert "removed_at = NULL" not in sql_flat


def test_soft_delete_method():
    conn = MockConn()
    conn._cursor._row = ("some",)  # fetchone returns a row → updated
    sink = PostgresSink(conn, table="t", soft_delete_col="removed_at")
    ok = sink.soft_delete(source="minfin", source_id="x")
    sql_flat = " ".join(conn._cursor.executed[0][0].split())
    assert "UPDATE t" in sql_flat
    assert "SET removed_at = NOW()" in sql_flat
    assert conn._cursor.executed[0][1] == ("minfin", "x")
    assert ok is True


def test_upsert_failure_returns_failed_and_rolls_back():
    class FailCursor(MockCursor):
        def execute(self, sql, params=None):
            raise RuntimeError("simulated DB error")

    class FailConn:
        def __init__(self):
            self._c = FailCursor()
            self.rolled_back = False

        def cursor(self):
            return self._c

        def rollback(self):
            self.rolled_back = True

    sink = PostgresSink(FailConn(), table="t")
    import asyncio

    result = asyncio.run(sink.upsert(_entity()))
    assert result.value == "failed"


def test_invalid_on_conflict_rejected():
    try:
        PostgresSink(MockConn(), table="t", on_conflict="DO_BAD_THING")
    except ValueError as exc:
        assert "DO_UPDATE or DO_NOTHING" in str(exc)
    else:
        raise AssertionError("expected ValueError")
