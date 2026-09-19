"""Telegram account pool: round-robin over session files, with real cooldown.

Extracted from benz's ``parsers_hybrid/telethon_parser.py``
(``AccountSlot`` at line 97, ``AccountPool`` at line 138) and, in the
process, fixing two real gaps measured there on 2026-09-19:

1. ``cooling_sec`` was declared (line 106) and read (lines 156, 164) but
   never *assigned* anywhere in that file — cooldown was dead on arrival,
   and quarantine of a bad account had to be done by hand via the
   ``BENZ_TG_ACCOUNTS`` env var. Here, :meth:`AccountSlot.penalize` is the
   single place that assigns it, and :meth:`AccountSlot.is_cooling` (which
   gates round-robin selection) reads that same field — so a test that
   removes the assignment sees the cooldown stop working.
2. ``FloodWaitError`` was never caught in that file — it appears only in
   comments (lines 9, 60); the real handling was a blanket
   ``except Exception`` (lines ~479-489). Here it is detected and handled
   *before* the generic exception path, and penalizes the slot for
   ``e.seconds`` instead of just bumping a failure counter.

``telethon`` stays an optional dependency of this library (it is not in
``pyproject.toml``'s ``dependencies``): the real ``FloodWaitError`` class is
imported opportunistically, and detection also falls back to matching the
exception's class name, so callers/tests can use a duck-typed
``FloodWaitError`` without installing telethon at all.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Callable, Sequence

try:  # pragma: no cover - exercised only when telethon is installed
    from telethon.errors.rpcerrorlist import FloodWaitError as _TelethonFloodWaitError
except ImportError:  # telethon is optional - not a hard dependency of this library
    _TelethonFloodWaitError = None  # type: ignore[assignment]


Clock = Callable[[], float]


def _is_flood_wait(exc: BaseException) -> bool:
    """True for telethon's ``FloodWaitError``.

    Detected by real isinstance check when telethon is installed, and by
    class name otherwise, so this also recognizes duck-typed test doubles
    named ``FloodWaitError`` with a ``.seconds`` attribute.
    """
    if _TelethonFloodWaitError is not None and isinstance(exc, _TelethonFloodWaitError):
        return True
    return type(exc).__name__ == "FloodWaitError"


class AllSlotsCoolingError(RuntimeError):
    """Raised by :meth:`AccountPool.acquire` when every slot is cooling down."""


class AccountSlot:
    """One Telegram account bound to a session file.

    Exactly one ``asyncio.Lock`` guards the session file, so two concurrent
    users of the *same* slot serialize, while two different slots (i.e.
    different session files) run in parallel.
    """

    def __init__(self, name: str, session_path: Path, *, now: Clock = time.monotonic):
        self.name = name
        self.session_path = session_path
        self.lock = asyncio.Lock()
        self._now = now
        self.success = 0
        self.fail = 0
        # Dead in the original benz file (assigned nowhere); here it is the
        # single field that both `penalize()` writes and `is_cooling()`
        # reads, so cooldown actually does something.
        self.cooling_sec: float = 0
        self._cooling_since: float = 0.0

    def is_cooling(self) -> bool:
        """True while this slot is serving out a penalty from `penalize()`."""
        if self.cooling_sec <= 0:
            return False
        return (self._now() - self._cooling_since) < self.cooling_sec

    def penalize(self, seconds: float) -> None:
        """Put this slot in cooldown for `seconds`, starting now."""
        self.cooling_sec = seconds
        self._cooling_since = self._now()

    @asynccontextmanager
    async def use(self) -> AsyncIterator["AccountSlot"]:
        """Hold this slot's lock for the duration of the `async with` block.

        FloodWaitError is caught separately from any other exception and
        penalizes the slot for `exc.seconds`; any other exception just
        counts as a failure. Both cases re-raise: this context manager
        reports, it does not swallow.
        """
        async with self.lock:
            try:
                yield self
            except Exception as exc:
                self.fail += 1
                if _is_flood_wait(exc):
                    self.penalize(getattr(exc, "seconds", 0) or 0)
                raise
            else:
                self.success += 1


class AccountPool:
    """Round-robin pool over a fixed list of `AccountSlot`."""

    def __init__(self, slots: Sequence[AccountSlot]):
        if not slots:
            raise ValueError("AccountPool requires at least one slot")
        self.slots: list[AccountSlot] = list(slots)
        self._rr_pos = 0

    def _next_available(self) -> AccountSlot:
        n = len(self.slots)
        for step in range(n):
            idx = (self._rr_pos + step) % n
            slot = self.slots[idx]
            if not slot.is_cooling():
                self._rr_pos = (idx + 1) % n
                return slot
        raise AllSlotsCoolingError(f"all {n} account slots are cooling down")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[AccountSlot]:
        """Pick the next available slot (round-robin, skipping cooldown) and
        hold its lock for the duration of the `async with` block."""
        slot = self._next_available()
        async with slot.use():
            yield slot
