"""`parser-cli run` — single-locator mode without sink."""

from __future__ import annotations

import asyncio
import json
import sys

from parser_universal.cli.shared import ADAPTERS
from parser_universal.rate_limiter.async_impl import AsyncRateLimiter


async def _run(adapter_name: str, locator: str) -> int:
    if adapter_name not in ADAPTERS:
        print(f"unknown adapter: {adapter_name}", file=sys.stderr)
        return 2
    adapter = ADAPTERS[adapter_name]()
    fetcher = adapter.source_safe_fetcher()
    rl = AsyncRateLimiter(rate_per_sec=2.0, burst=4)
    record = await adapter.fetch_one(locator, fetcher=fetcher, rate_limiter=rl)
    if record is None:
        print("adapter returned None (skip / not found)", file=sys.stderr)
        return 1
    out = {
        "source": record.source,
        "source_id": record.source_id,
        "raw_ref": record.raw_ref,
        "coord_hint": record.coord_hint,
        "text_preview": (record.text or "")[:200] if record.text else None,
        "fetched_at": record.fetched_at.isoformat(),
        "raw_size": len(record.raw.get("body", b"")) if "body" in record.raw else None,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_run(args) -> int:
    return asyncio.run(_run(args.adapter, args.locator))
