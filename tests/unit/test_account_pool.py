"""Unit tests for the Telegram account pool (parser_universal.sources.telegram).

Covers the two gaps this module fixes relative to benz's
parsers_hybrid/telethon_parser.py (2026-09-19 measurement):
  1. cooling_sec was dead (initialized, read, never assigned) — a FloodWait
     must actually move a slot out of rotation until its cooldown elapses,
     with no real `sleep` (time is injected via `now=`).
  2. FloodWaitError was never caught (only mentioned in comments; real
     handling was a blanket `except Exception`).

Also covers the underlying lock contract: one asyncio.Lock per session
file, so the same slot serializes concurrent use and different slots run
in parallel.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from parser_universal.sources.telegram.account_pool import (
    AccountPool,
    AccountSlot,
    AllSlotsCoolingError,
)


class FloodWaitError(Exception):
    """Local duck-type of telethon's FloodWaitError — telethon is not
    installed in this library's test env, and must not be required."""

    def __init__(self, seconds: float):
        super().__init__(f"flood wait {seconds}s")
        self.seconds = seconds


class FakeClock:
    """Injectable `now()` — advances only when the test tells it to."""

    def __init__(self, start: float = 1000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _slot(name: str, clock: FakeClock) -> AccountSlot:
    return AccountSlot(name, Path(f"/fake/{name}.session"), now=clock)


# ── Acceptance (1): FloodWait quarantines the slot, round-robin skips it ────


@pytest.mark.asyncio
async def test_floodwait_penalizes_slot_and_pool_hands_out_the_other_one():
    clock = FakeClock()
    a, b = _slot("a", clock), _slot("b", clock)
    pool = AccountPool([a, b])

    with pytest.raises(FloodWaitError):
        async with pool.acquire() as slot:
            assert slot is a
            raise FloodWaitError(seconds=100)

    assert a.cooling_sec == 100
    assert a.is_cooling() is True

    # Immediately after: A is cooling, so acquire() must hand out B.
    async with pool.acquire() as slot2:
        assert slot2 is b

    # Cooldown not yet elapsed (50s of 100s) — A still refused.
    clock.advance(50)
    assert a.is_cooling() is True
    async with pool.acquire() as slot3:
        assert slot3.name != "a"

    # Cooldown elapsed (110s > 100s) — A is available again, no real sleep.
    clock.advance(60)
    assert a.is_cooling() is False
    async with pool.acquire() as slot4:
        assert slot4 is a


@pytest.mark.asyncio
async def test_all_slots_cooling_raises_instead_of_hanging():
    clock = FakeClock()
    a, b = _slot("a", clock), _slot("b", clock)
    pool = AccountPool([a, b])
    a.penalize(10)
    b.penalize(10)

    with pytest.raises(AllSlotsCoolingError):
        async with pool.acquire():
            pass  # pragma: no cover - must not be reached


@pytest.mark.asyncio
async def test_non_floodwait_exception_counts_as_failure_but_no_cooldown():
    clock = FakeClock()
    a = _slot("a", clock)
    pool = AccountPool([a])

    with pytest.raises(RuntimeError):
        async with pool.acquire():
            raise RuntimeError("boom")

    assert a.fail == 1
    assert a.cooling_sec == 0
    assert a.is_cooling() is False


# ── Acceptance (2): one lock per session file — serialize / parallelize ────


@pytest.mark.asyncio
async def test_same_session_file_serializes_concurrent_use():
    clock = FakeClock()
    a = _slot("a", clock)
    order: list[str] = []
    release = asyncio.Event()

    async def first():
        async with a.use():
            order.append("first-start")
            await release.wait()
            order.append("first-end")

    async def second():
        async with a.use():
            order.append("second-start")
            order.append("second-end")

    t1 = asyncio.create_task(first())
    await asyncio.sleep(0)  # let first() acquire the lock (no timed wait)
    t2 = asyncio.create_task(second())
    await asyncio.sleep(0)  # give second() a chance to run — it must block

    assert order == ["first-start"]  # second() is stuck behind the same lock

    release.set()
    await t1
    await t2

    assert order == ["first-start", "first-end", "second-start", "second-end"]


@pytest.mark.asyncio
async def test_different_session_files_run_in_parallel():
    clock = FakeClock()
    a, b = _slot("a", clock), _slot("b", clock)
    order: list[str] = []
    a_started, b_started = asyncio.Event(), asyncio.Event()

    async def use_a():
        async with a.use():
            order.append("a-start")
            a_started.set()
            # Would deadlock here if b's lock were the same one as a's.
            await b_started.wait()
            order.append("a-end")

    async def use_b():
        async with b.use():
            order.append("b-start")
            b_started.set()
            await a_started.wait()
            order.append("b-end")

    await asyncio.wait_for(asyncio.gather(use_a(), use_b()), timeout=2.0)

    assert set(order[:2]) == {"a-start", "b-start"}


# ── Round-robin sanity ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_round_robin_cycles_slots_in_order():
    clock = FakeClock()
    a, b, c = _slot("a", clock), _slot("b", clock), _slot("c", clock)
    pool = AccountPool([a, b, c])

    picked = []
    for _ in range(4):
        async with pool.acquire() as slot:
            picked.append(slot.name)

    assert picked == ["a", "b", "c", "a"]


def test_empty_pool_rejected():
    with pytest.raises(ValueError):
        AccountPool([])
