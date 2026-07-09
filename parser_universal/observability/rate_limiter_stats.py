"""Rate-limiter stats: JSON-file snapshot of token bucket state.

Useful for ops dashboards / cron health-checks.

Schema (JSON file):
{
  "ts": "2026-07-06T09:55:00Z",
  "rate_per_sec": 2.0,
  "burst": 4,
  "current_interval_s": 0.5,
  "tokens_available": 3.14,
  "backoff_active": false,
  "by_status": {"200": 142, "429": 0, "503": 1}
}
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class RateLimiterStats:
    """Thread-safe counter + periodic dumper.

    Wrap your RateLimiter: every time you call `report(status)`, also feed
    the stats collector. Dumper writes JSON on `dump()` or every N seconds
    via `start_periodic_dump()`.
    """

    def __init__(self, path: Path | str, *, rate_per_sec: float, burst: int) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rate_per_sec = rate_per_sec
        self.burst = burst
        self._lock = threading.Lock()
        self._by_status: Counter[int] = Counter()
        self._start_ts = time.time()

    def record(self, status: int) -> None:
        with self._lock:
            self._by_status[status] += 1

    def snapshot(self, *, current_interval_s: float, tokens_available: float) -> dict[str, Any]:
        with self._lock:
            elapsed = max(0.001, time.time() - self._start_ts)
            return {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "uptime_s": round(elapsed, 1),
                "rate_per_sec": self.rate_per_sec,
                "burst": self.burst,
                "current_interval_s": round(current_interval_s, 4),
                "tokens_available": round(tokens_available, 3),
                "backoff_active": current_interval_s > (1.0 / self.rate_per_sec) * 1.05,
                "by_status": {str(k): v for k, v in sorted(self._by_status.items())},
            }

    def dump(self, *, current_interval_s: float, tokens_available: float) -> None:
        snap = self.snapshot(
            current_interval_s=current_interval_s, tokens_available=tokens_available
        )
        try:
            self.path.write_text(json.dumps(snap, indent=2, ensure_ascii=False))
        except OSError as exc:
            log.warning("rate_limiter_stats: dump failed: %s", exc)


__all__ = ["RateLimiterStats"]
