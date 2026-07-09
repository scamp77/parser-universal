"""Sink protocol — every destination implements this.

Sinks are intentionally simple: they take a DomainEntity and persist it.
Cross-cutting concerns (FailureSink, orchestration) are layered elsewhere.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable

from parser_universal.types import DomainEntity


class EntityResult(str, Enum):
    """Outcome of an upsert — drives orchestrator counters + observability."""

    INSERTED = "inserted"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


@runtime_checkable
class Sink(Protocol):
    """Protocol for any destination."""

    name: str

    async def upsert(self, entity: DomainEntity) -> EntityResult:
        """Persist or update the entity. Returns outcome."""
        ...
