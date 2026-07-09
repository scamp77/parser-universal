"""YAML declarative config — `parser-cli run --config=...yaml`.

Phase 4 deliverable. Schema:

    adapter:
      name: gpx|url|html|api|overpass
      locator: tests/data/sample.gpx           # OR list locators below

    locators:                                  # optional list
      - tests/data/foo.gpx
      - tests/data/bar.gpx

    sink:
      type: dryrun|postgres
      table: entities                          # postgres only

    enrichers:
      - brouter
      - <future-enricher>

    failure_sink: true                         # only when sink=postgres

    daily_log: true                            # only when sink=postgres

    fetcher:
      persistent: true                         # Phase 4 — reuse httpx client
      strategies:
        - httpx_persistent
        - httpx
        - jina_fallback

    rate_limiter:
      rate_per_sec: 2.0
      burst: 4

    parallel:
      workers: 1                               # Phase 4 — gather with semaphore
      batch_size: 32

Load YAML → dict; build orchestrator; mirror of CLI flags.

Reference precedent: per `MEMORY-session-close-2026-07-06-parser-universal.md`,
both library + CLI forms are exposed for cross-project reuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ParallelConfig:
    workers: int = 1
    batch_size: int = 32


@dataclass
class RateLimiterConfig:
    rate_per_sec: float = 2.0
    burst: int = 4


@dataclass
class FetcherConfig:
    persistent: bool = True
    strategies: list[str] = field(
        default_factory=lambda: ["httpx_persistent", "jina_fallback"]
    )


@dataclass
class SinkConfig:
    type: str = "dryrun"
    table: str = "entities"


@dataclass
class ParserConfig:
    """Validated representation of a YAML config file."""

    adapter: str
    locator: str | None = None
    locators: list[str] = field(default_factory=list)
    sink: SinkConfig = field(default_factory=SinkConfig)
    enrichers: list[str] = field(default_factory=list)
    failure_sink: bool = False
    daily_log: bool = False
    fetcher: FetcherConfig = field(default_factory=FetcherConfig)
    rate_limiter: RateLimiterConfig = field(default_factory=RateLimiterConfig)
    parallel: ParallelConfig = field(default_factory=ParallelConfig)
    source_name: str | None = None

    def all_locators(self) -> list[str]:
        if self.locators:
            return list(self.locators)
        if self.locator:
            return [self.locator]
        return []


def load_config(path: str | Path) -> dict[str, Any]:
    """Parse YAML config file → raw dict. Raises FileNotFoundError / YAMLError."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    return yaml.safe_load(p.read_text())


def validate_config(d: dict[str, Any]) -> ParserConfig:
    """Validate raw dict → typed ParserConfig. Raises ValueError on schema error."""
    if not isinstance(d, dict):
        raise ValueError("top-level must be a mapping")
    adapter = d.get("adapter")
    if not adapter or not isinstance(adapter, str):
        raise ValueError("`adapter` is required and must be a string")
    cfg = ParserConfig(adapter=adapter)

    if "locator" in d:
        cfg.locator = str(d["locator"])
    if "locators" in d:
        if not isinstance(d["locators"], list):
            raise ValueError("`locators` must be a list")
        cfg.locators = [str(x) for x in d["locators"]]

    if "sink" in d and isinstance(d["sink"], dict):
        sink_d = d["sink"]
        cfg.sink = SinkConfig(
            type=sink_d.get("type", "dryrun"),
            table=sink_d.get("table", "entities"),
        )

    if "enrichers" in d:
        if not isinstance(d["enrichers"], list):
            raise ValueError("`enrichers` must be a list")
        cfg.enrichers = [str(e) for e in d["enrichers"]]

    cfg.failure_sink = bool(d.get("failure_sink", False))
    cfg.daily_log = bool(d.get("daily_log", False))

    if "fetcher" in d and isinstance(d["fetcher"], dict):
        f = d["fetcher"]
        strategies = f.get("strategies", ["httpx_persistent", "jina_fallback"])
        if not isinstance(strategies, list):
            raise ValueError("`fetcher.strategies` must be a list")
        cfg.fetcher = FetcherConfig(
            persistent=bool(f.get("persistent", True)),
            strategies=[str(s) for s in strategies],
        )

    if "rate_limiter" in d and isinstance(d["rate_limiter"], dict):
        rl = d["rate_limiter"]
        cfg.rate_limiter = RateLimiterConfig(
            rate_per_sec=float(rl.get("rate_per_sec", 2.0)),
            burst=int(rl.get("burst", 4)),
        )

    if "parallel" in d and isinstance(d["parallel"], dict):
        p = d["parallel"]
        cfg.parallel = ParallelConfig(
            workers=int(p.get("workers", 1)),
            batch_size=int(p.get("batch_size", 32)),
        )

    cfg.source_name = d.get("source_name")
    return cfg


__all__ = [
    "ParallelConfig",
    "RateLimiterConfig",
    "FetcherConfig",
    "SinkConfig",
    "ParserConfig",
    "load_config",
    "validate_config",
]
