"""DirectOverpassFetcher — Persistent httpx clients per Overpass mirror.

Урок benchmark 2026-07-28 (см. /tmp/bench_v1_v2.py):
  - Бесплатные HTTP прокси из bypass-tools pool полностью недоступны
    из текущего host (firewall блокирует исходящие к non-standard портам).
  - Прямой запрос к maps.mail.ru (Overpass mirror) — 1.3-7s, 100% success.
  - Per-call AsyncClient = TCP/TLS handshake на каждый тайл (200-500ms waste).

Дизайн:
  - Один Persistent httpx.AsyncClient на Overpass mirror
  - mirror failover: tried mirrors сохраняются с exponential backoff cooldown
    (mail.ru успех → cooldown 0; после 406 → cooldown 60s; после 504 → 30s)
  - POST с data={"data": query} — нет URL-length limit (vs GET ?data=...)
  - mirror health: latest_status + last_success_ts; при выборе пропускаем
    mirror'ы в cooldown

Использование:
    fetcher = DirectOverpassFetcher()
    data = await fetcher.fetch(OVERPASS_QUERY_TEMPLATE.format(bbox=...))
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

OVERPASS_MIRRORS = (
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)

DEFAULT_TIMEOUT_S = 35.0
DEFAULT_COOLDOWN_S = 60.0
DEFAULT_HEALTH_CHECK_TTL_S = 30.0


@dataclass
class MirrorHealth:
    url: str
    client: httpx.AsyncClient | None = None
    last_status: int = 0
    last_success_ts: float = 0.0
    last_attempt_ts: float = 0.0
    consecutive_failures: int = 0
    cooldown_until_ts: float = 0.0

    def is_usable(self) -> bool:
        return time.monotonic() >= self.cooldown_until_ts

    def cooldown_remaining_s(self) -> float:
        return max(0.0, self.cooldown_until_ts - time.monotonic())


class DirectOverpassFetcher:
    """Persistent-client Overpass fetcher с mirror failover."""

    def __init__(self, mirrors: tuple[str, ...] = OVERPASS_MIRRORS):
        self.mirrors: dict[str, MirrorHealth] = {
            url: MirrorHealth(url=url) for url in mirrors
        }
        self._lock = asyncio.Lock()

    async def _get_client(self, mh: MirrorHealth) -> httpx.AsyncClient:
        if mh.client is None:
            mh.client = httpx.AsyncClient(
                timeout=httpx.Timeout(DEFAULT_TIMEOUT_S, connect=10.0),
                follow_redirects=True,
                headers={"User-Agent": "benz-overpass/1.0 (+https://github.com/scamp77/benz)"},
            )
        return mh.client

    async def _pick_mirror(self) -> MirrorHealth | None:
        async with self._lock:
            usable = [mh for mh in self.mirrors.values() if mh.is_usable()]
            if not usable:
                # Reset cooldowns, попробуем снова
                for mh in self.mirrors.values():
                    mh.cooldown_until_ts = 0.0
                usable = list(self.mirrors.values())
            if not usable:
                return None
            # Prefer mirror с самым свежим last_success_ts, fallback на first
            usable.sort(key=lambda m: m.last_success_ts, reverse=True)
            return usable[0]

    def _record_success(self, mh: MirrorHealth, ms: float):
        mh.last_status = 200
        mh.last_success_ts = time.monotonic()
        mh.last_attempt_ts = time.monotonic()
        mh.consecutive_failures = 0
        mh.cooldown_until_ts = 0.0

    def _record_failure(self, mh: MirrorHealth, status: int):
        mh.last_status = status
        mh.last_attempt_ts = time.monotonic()
        mh.consecutive_failures += 1
        if status in (502, 503, 504):
            mh.cooldown_until_ts = time.monotonic() + DEFAULT_COOLDOWN_S
        elif status == 406:
            mh.cooldown_until_ts = time.monotonic() + DEFAULT_COOLDOWN_S * 2
        elif status >= 500:
            mh.cooldown_until_ts = time.monotonic() + DEFAULT_COOLDOWN_S

    async def fetch(self, query: str) -> dict:
        """Try mirrors until one succeeds; raise if all fail."""
        last_exc: Exception | None = None
        tried: list[str] = []
        for attempt in range(len(self.mirrors)):
            mh = await self._pick_mirror()
            if mh is None or mh.url in tried:
                # Все mirrors в cooldown / exhausted — попробуем reset и снова
                if tried:
                    break
                continue
            tried.append(mh.url)

            client = await self._get_client(mh)
            t0 = time.monotonic()
            try:
                # POST is preferred: bypasses URL length limit + some mirrors
                # are stricter on GET (overpass-api.de 406). Use POST when
                # mirror accepts it; fall back to GET if POST returns 405.
                resp = await client.post(mh.url, data={"data": query})
            except Exception as exc:
                ms = (time.monotonic() - t0) * 1000
                log.warning("mirror=%s EXC %s ms=%.0f", mh.url, exc.__class__.__name__, ms)
                last_exc = exc
                mh.consecutive_failures += 1
                mh.cooldown_until_ts = time.monotonic() + DEFAULT_COOLDOWN_S
                continue

            ms = (time.monotonic() - t0) * 1000

            if 200 <= resp.status_code < 300:
                self._record_success(mh, ms)
                return resp.json()

            log.warning(
                "mirror=%s status=%d ms=%.0f body[:100]=%r",
                mh.url, resp.status_code, ms, resp.content[:100],
            )
            self._record_failure(mh, resp.status_code)
            last_exc = RuntimeError(f"{mh.url} returned {resp.status_code}")

        raise RuntimeError(
            f"all {len(self.mirrors)} Overpass mirrors failed; last_exc={last_exc}"
        )

    async def aclose(self):
        for mh in self.mirrors.values():
            if mh.client is not None:
                try:
                    await mh.client.aclose()
                except Exception:
                    pass
                mh.client = None

    def stats(self) -> dict:
        return {
            url: {
                "last_status": mh.last_status,
                "consecutive_failures": mh.consecutive_failures,
                "cooldown_remaining_s": round(mh.cooldown_remaining_s(), 1),
                "last_success_ts": mh.last_success_ts,
            }
            for url, mh in self.mirrors.items()
        }
