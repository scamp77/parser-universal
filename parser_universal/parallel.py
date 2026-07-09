"""Parallel batch runner — `asyncio.gather` + Semaphore.

Phase 4 deliverable.

Per `MEMORY-benz-rules-extracted.md`:
- Sequential batch parsers (load_energy, load_bridges) had pool-init races
  with multiprocess parallelism.
- Solution: **asyncio.gather + shared event loop + semaphore**, NOT
  multiprocessing. Same event loop keeps connection pool coherent.

This module wraps `ParserOrchestrator.run()` with `asyncio.gather` over
chunks, gated by a `Semaphore(max_workers)`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Iterable

log = logging.getLogger(__name__)


async def gather_with_semaphore(
    items: Iterable,
    worker: Callable,
    *,
    max_workers: int = 4,
    batch_size: int = 32,
) -> list:
    """Run `worker(item)` concurrently, gated by a Semaphore.

    Args:
        items: iterable of items to process.
        worker: async callable (item) → result.
        max_workers: maximum concurrent workers.
        batch_size: how many items per gather batch (yields control between
                    batches, useful for long-running jobs).

    Returns:
        list of results in the order items were submitted.
    """
    semaphore = asyncio.Semaphore(max_workers)
    items_list = list(items)

    async def _gated(item):
        async with semaphore:
            return await worker(item)

    results: list = []
    for i in range(0, len(items_list), batch_size):
        chunk = items_list[i : i + batch_size]
        chunk_results = await asyncio.gather(*[_gated(x) for x in chunk])
        results.extend(chunk_results)
    return results


__all__ = ["gather_with_semaphore"]
