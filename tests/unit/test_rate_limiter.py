"""Unit tests for sync RateLimiter (drop-in from sup-app)."""

import time

import pytest

from parser_universal.rate_limiter.sync_impl import RateLimiter


def test_initial_burst_is_full():
    rl = RateLimiter(rate_per_sec=2.0, burst=4)
    # First burst tokens should be available immediately.
    for _ in range(4):
        rl.acquire(timeout=1.0)
    # 5th should block briefly, so a short timeout must fail.
    with pytest.raises(TimeoutError):
        rl.acquire(timeout=0.05)


def test_acquire_after_refill():
    rl = RateLimiter(rate_per_sec=10.0, burst=2)
    rl.acquire()
    rl.acquire()
    # After ~0.2s we should have refilled one token.
    time.sleep(0.25)
    rl.acquire(timeout=1.0)  # should not raise


def test_report_backoff_doubles_interval():
    rl = RateLimiter(rate_per_sec=2.0, burst=4)
    initial = rl.current_interval
    rl.report(503)
    assert rl.current_interval == initial * 2.0
    assert rl.tokens == 0.0


def test_report_429_backs_off():
    rl = RateLimiter(rate_per_sec=2.0, burst=4)
    initial = rl.current_interval
    rl.report(429)
    assert rl.current_interval == initial * 2.0


def test_backoff_capped_at_60s():
    rl = RateLimiter(rate_per_sec=2.0, burst=4)
    # Many backoffs → should cap at 60s.
    for _ in range(20):
        rl.report(503)
    assert rl.current_interval <= 60.0


def test_success_relaxes_backoff():
    rl = RateLimiter(rate_per_sec=4.0, burst=4)
    # Force into backoff.
    rl.report(503)
    assert rl.current_interval > rl.base_interval
    # Pretend 30s passed by manipulating _last_success.
    rl._last_success = time.monotonic() - 31.0
    rl.report(200)
    # Should have relaxed toward base (or be at base).
    assert rl.current_interval <= rl.base_interval * 2.0


def test_acquire_respects_timeout():
    rl = RateLimiter(rate_per_sec=1.0, burst=1)
    rl.acquire()
    # No tokens; long timeout → TimeoutError eventually.
    with pytest.raises(TimeoutError):
        rl.acquire(timeout=0.05)
