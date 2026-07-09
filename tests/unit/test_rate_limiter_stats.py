"""Unit tests for observability/rate_limiter_stats.py.

Just verifies the snapshot dict shape — no real RL interaction needed.
"""

import json
from parser_universal.observability.rate_limiter_stats import RateLimiterStats


def test_snapshot_shape(tmp_path):
    p = tmp_path / "stats.json"
    stats = RateLimiterStats(p, rate_per_sec=2.0, burst=4)
    stats.record(200)
    stats.record(200)
    stats.record(429)
    snap = stats.snapshot(current_interval_s=0.5, tokens_available=3.0)
    assert snap["rate_per_sec"] == 2.0
    assert snap["burst"] == 4
    assert snap["current_interval_s"] == 0.5
    assert snap["tokens_available"] == 3.0
    assert snap["backoff_active"] is False
    assert snap["by_status"] == {"200": 2, "429": 1}


def test_dump_writes_valid_json(tmp_path):
    p = tmp_path / "stats.json"
    stats = RateLimiterStats(p, rate_per_sec=4.0, burst=8)
    stats.record(200)
    stats.dump(current_interval_s=0.25, tokens_available=5.5)
    payload = json.loads(p.read_text())
    assert payload["rate_per_sec"] == 4.0
    assert payload["burst"] == 8
    assert payload["by_status"] == {"200": 1}


def test_backoff_flag_flips(tmp_path):
    p = tmp_path / "stats.json"
    stats = RateLimiterStats(p, rate_per_sec=1.0, burst=2)
    # current_interval > base * 1.05 → backoff active
    snap = stats.snapshot(current_interval_s=3.0, tokens_available=0.5)
    assert snap["backoff_active"] is True
