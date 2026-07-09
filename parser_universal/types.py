"""Canonical types shared between layers.

Frozen dataclasses — pure value objects, safe to pass across adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RawRecord:
    """Canonical shape after Layer 1 (Input adapter).

    All adapters return this regardless of source.
    """

    source: str  # 'okko' / 'wikiloc' / 't.me_preview' / 'minfin' / ...
    source_id: str  # vendor-specific immutable id (dedup key)
    raw: dict[str, Any]  # vendor-specific full payload
    fetched_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    raw_ref: str = ""  # 'url' or 'source:channel_id:msg_id'
    coord_hint: tuple[float, float] | None = None  # (lat, lon)
    text: str | None = None
    media_url: str | None = None


@dataclass(frozen=True)
class DomainEntity:
    """Canonical domain entity (Route / Station / Product / Article).

    Produced by Layer 2 (Normalizer), enriched in Layer 3, persisted in Layer 4.
    """

    entity_type: str  # 'route' / 'gas_station' / 'product' / 'poi'
    source: str  # passthrough from RawRecord
    source_id: str
    geom: tuple[float, float] | None = None  # (lat, lon), main point
    attrs: dict[str, Any] = field(default_factory=dict)
    bbox_country: str | None = None  # computed in Layer 2
    confidence: float = 1.0


@dataclass(frozen=True)
class FetchResult:
    """Result of a single HTTP fetch (one strategy attempt)."""

    url: str
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    elapsed_ms: int = 0
    strategy: str = ""  # 'httpx' / 'curl_cffi' / 'jina' / 'wayback' / ...


@dataclass(frozen=True)
class RetryPolicy:
    """Retry knobs.

    Validated pattern from sup-app T1.4 PR #74 (jina_retry).
    """

    max_retries: int = 2
    backoff_factor: float = 1.5
    initial_backoff_s: float = 2.0
    retry_on_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504})
    sleep_before_request_s: float = 0.6  # Jina politeness
    retry_on_timeout: bool = True
    retry_on_connection_reset: bool = True


DEFAULT_RETRY = RetryPolicy()
