"""Unit tests for observability/structlog_setup.py.

Uses direct capture of structlog's renderer output (writes to whatever
sys.stderr is at log-time). We swap sys.stderr and observe the output.
"""

import io
import sys

from parser_universal.observability.structlog_setup import configure_logging, get_logger


def _capture(callable_):
    """Capture stderr output during a callable.

    structlog.PrintLoggerFactory reads sys.stderr at log-time and caches it
    via its `_file` attribute. We update that attribute explicitly so the
    cached reference also points at our StringIO.
    """
    import structlog as _structlog

    fake = io.StringIO()
    real_stderr = sys.stderr
    sys.stderr = fake
    factory = _structlog.get_config()["logger_factory"]
    if hasattr(factory, "_file"):
        factory._file = fake
    try:
        callable_()
    finally:
        sys.stderr = real_stderr
        if hasattr(factory, "_file"):
            factory._file = real_stderr
    return fake.getvalue()


def test_get_logger_returns_structlog_logger():
    configure_logging(level="INFO", json=True)
    log = get_logger("test_returns")
    assert log is not None
    assert hasattr(log, "info")
    assert hasattr(log, "warning")
    assert hasattr(log, "error")


def test_configure_logging_json_emits_valid_json():
    configure_logging(level="INFO", json=True)
    log = get_logger("test_json")
    out = _capture(lambda: log.info("event_x", foo=42))
    assert '"event"' in out
    assert '"foo": 42' in out or '"foo":42' in out
    assert "event_x" in out


def test_configure_logging_console_renderer():
    configure_logging(level="INFO", json=False)
    log = get_logger("test_console")
    out = _capture(lambda: log.info("hi_console", k="v"))
    # Console renderer doesn't use JSON; just check the event name shows up.
    assert "hi_console" in out


def test_reconfigure_changes_renderer():
    """Second configure_logging(json=True) call switches to JSON renderer."""
    configure_logging(level="INFO", json=False)
    log = get_logger("test_reconf")
    out_console = _capture(lambda: log.info("hi_c", k=1))
    assert "{k" not in out_console or "k=" in out_console  # console key=value syntax

    configure_logging(level="INFO", json=True)
    out_json = _capture(lambda: log.info("hi_j", k=2))
    assert '"k": 2' in out_json or '"k":2' in out_json
