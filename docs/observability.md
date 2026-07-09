# Observability

Three observability channels are wired by default. All write to stderr in
JSON format via structlog.

## structlog

`parser_universal.observability.structlog_setup` configures structlog
to emit JSON records (`event`, `level`, `timestamp`, `module`, plus
custom kwargs). Override via `UP_LOG_FORMAT=console` for human-readable
output.

Each orchestrator run emits:

```json
{
  "event": "orchestrator.run_done",
  "source": "minfin",
  "total": 1,
  "inserted": 1,
  "updated": 0,
  "skipped": 0,
  "failed": 0,
  "duration_ms": 47
}
```

## daily_source_log

`parser_universal.observability.daily_source_log.DailySourceLog` writes
one row per parser-run to the `daily_source_log` table:

| column        | meaning                                  |
|---------------|------------------------------------------|
| `source`      | parser name (`minfin_detail`, `url`, …)  |
| `rows_added`  | count of INSERTED outcomes               |
| `rows_updated`| count of UPDATED outcomes                |
| `http_status` | last HTTP status seen                    |
| `error`       | first error (or `k=v|k=v` diagnostics)   |
| `duration_ms` | wall-clock run duration                  |

The `error` column carries diagnostics as `|`-separated `k=v` pairs:

```
channels_ok=10|channels_empty=2|channels_err=0|duration_s=12
```

Per benz durable rule: **NO `raw` column** on `daily_source_log`.

## rate_limiter_stats

`parser_universal.observability.rate_limiter_stats.RateLimiterStats`
writes a JSON snapshot of the rate-limiter state every `dump()` call:

```json
{
  "ts": "2026-07-06T10:00:00Z",
  "rate_per_sec": 2.0,
  "burst": 4,
  "current_interval_s": 0.5,
  "tokens_available": 3.14,
  "backoff_active": false,
  "by_status": {"200": 142, "429": 0, "503": 1}
}
```

For cron scripts the recommended pattern is:

1. Run the parser CLI
2. After exit, dump stats via `RateLimiterStats(path).dump(...)`
3. Health-check script queries `daily_source_log` for last-7-days rows

Matches the benz `scripts/health_check.sh` pattern (durable rule:
cron-script-before-cron).
