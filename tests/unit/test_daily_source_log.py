"""Unit tests for DailySourceLog — uses a mock conn (no Postgres needed).

Pattern verified against benz `load_minfin_prices.py:_log_source_run` and
`telegram_preview.py:_log_run`.
"""

from parser_universal.observability.daily_source_log import DailySourceLog


class MockCursor:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def commit(self):
        self.committed = True


class MockConn:
    """Mock that exposes `.execute()` directly (psycopg3 Connection style).

    Note: psycopg3.Connection.execute is the canonical entrypoint — it opens
    an internal cursor under the hood. DailySourceLog uses `.execute()` directly.
    """

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def commit(self):
        self.commits += 1


def test_write_basic_row():
    conn = MockConn()
    DailySourceLog(conn).write(
        source="minfin_detail",
        rows_added=10,
        rows_updated=2,
        http_status=200,
        error=None,
        duration_ms=420,
    )
    sql, params = conn.executed[0]
    assert "INSERT INTO daily_source_log" in sql
    assert "(source, rows_added, rows_updated, http_status, error, duration_ms)" in sql
    assert params == ("minfin_detail", 10, 2, 200, None, 420)
    # No auto-commit (caller-managed transaction, per benz pattern).


def test_write_diag_packs_into_error():
    conn = MockConn()
    DailySourceLog(conn).write_diag(
        source="telegram_preview",
        rows_added=3,
        rows_updated=0,
        http_status=200,
        duration_ms=1500,
        diag={
            "channels_ok": 10,
            "channels_empty": 1,
            "channels_err": 0,
            "duration_s": 1.5,
        },
    )
    sql, params = conn.executed[0]
    err = params[4]
    assert err is not None
    assert "channels_ok=10" in err
    assert "channels_empty=1" in err
    assert "channels_err=0" in err


def test_write_diag_with_error_prefix():
    conn = MockConn()
    DailySourceLog(conn).write_diag(
        source="x",
        rows_added=0,
        rows_updated=0,
        http_status=503,
        duration_ms=10,
        diag={"k": 1},
        error_prefix="HTTP 503",
    )
    sql, params = conn.executed[0]
    err = params[4]
    assert err.startswith("HTTP 503 | ")
    assert "k=1" in err


def test_supports_execute_protocol_match():
    conn = MockConn()
    from parser_universal.observability.daily_source_log import SupportsExecute
    assert isinstance(conn, SupportsExecute) is True  # has execute + commit


def test_no_autocommit_by_daily_log_itself():
    """DailySourceLog does NOT auto-commit — caller manages the transaction.

    (Matches benz pattern: `with get_conn() as conn` then explicit `.commit()`.)
    """
    conn = MockConn()
    DailySourceLog(conn).write(
        source="x",
        rows_added=0,
        rows_updated=0,
        http_status=None,
        error=None,
        duration_ms=0,
    )
    assert conn.commits == 0
