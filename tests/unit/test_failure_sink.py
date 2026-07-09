"""Unit tests for FailureSink — uses mock cursor.

Verifies the (source, source_id) idempotent UPSERT with attempts counter,
matching sup-app `v2.raw_routes_failed` pattern (`record_failed_route`).
"""

from __future__ import annotations

from parser_universal.sinks.failure import FailureSink
from parser_universal.types import RawRecord


class MockCursor:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))


class MockConn:
    def __init__(self):
        self._cursor = MockCursor()
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _raw(**overrides):
    base = dict(
        source="okko",
        source_id="okko-station-123",
        raw={"region": "Kyiv"},
        coord_hint=(50.45, 30.52),
        raw_ref="https://okko.ua/station/123",
        text="Some title",
    )
    base.update(overrides)
    return RawRecord(**base)


def test_record_failure_inserts_row():
    conn = MockConn()
    FailureSink(conn, table="raw_routes_failed").record(
        _raw(), stage="fetch", detail="HTTP 503"
    )
    sql, params = conn._cursor.executed[0]
    assert "INSERT INTO raw_routes_failed" in sql
    assert "ON CONFLICT (source, source_id) DO UPDATE" in sql
    assert "raw_routes_failed.attempts + 1" in sql  # counter increment
    assert "last_attempt_at = NOW()" in sql
    assert params[0] == "okko"
    assert params[1] == "okko-station-123"
    assert params[2] == "Some title"
    assert params[3] == "https://okko.ua/station/123"
    assert params[5] == "fetch"
    assert params[6] == "HTTP 503"
    assert conn.commits == 1


def test_record_failure_without_coord():
    conn = MockConn()
    FailureSink(conn).record(
        _raw(coord_hint=None), stage="parse", detail="no coord"
    )
    geom_param = conn._cursor.executed[0][1][4]
    assert geom_param is None


def test_record_failure_truncates_detail():
    conn = MockConn()
    FailureSink(conn).record(
        _raw(), stage="parse", detail="x" * 5000,
    )
    detail_param = conn._cursor.executed[0][1][6]
    assert len(detail_param) == 2000  # truncated to 2000


def test_record_failure_non_url_raw_ref_becomes_none():
    conn = MockConn()
    FailureSink(conn).record(_raw(raw_ref="telegram:channel:42"), stage="fetch", detail="x")
    url_param = conn._cursor.executed[0][1][3]
    assert url_param is None


def test_record_failure_db_error_does_not_propagate():
    class BoomCursor(MockCursor):
        def execute(self, sql, params=None):
            raise RuntimeError("simulated")

    class BoomConn:
        def __init__(self):
            self._c = BoomCursor()

        def cursor(self):
            return self._c

        def rollback(self):
            pass

    # Should NOT raise — FailureSink is best-effort.
    FailureSink(BoomConn()).record(_raw(), stage="persist", detail="x")
