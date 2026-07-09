"""PostgresSink — generic async psycopg3 sink with ON CONFLICT + JSONB merge + soft-delete.

Schema pattern (recommended; configurable per-instance):

  CREATE TABLE IF NOT EXISTS v3.routes (
      id            BIGSERIAL PRIMARY KEY,
      source        TEXT NOT NULL,
      source_id     TEXT NOT NULL,
      entity_type   TEXT NOT NULL,
      geom          GEOMETRY(Point, 4326),
      attrs         JSONB NOT NULL DEFAULT '{}'::jsonb,
      bbox_country  TEXT,
      confidence    REAL DEFAULT 1.0,
      last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      removed_at    TIMESTAMPTZ,           -- soft-delete (benz durable rule)
      UNIQUE (source, source_id)
  );
  CREATE INDEX ... (geom);  -- PostGIS optional; if present, GEOMETRY(Point, 4326)
                             -- if absent, store as JSON array {lat, lon} in attrs.

Upsert behavior:
  - On conflict (source, source_id): merge attrs (JSONB ||), update last_seen_at,
    CLEAR removed_at (re-activation), increment nothing.
  - On no conflict: insert all fields including bbox_country (auto-computed if
    geom provided).
  - Soft-delete on `upsert(removed=True, ...)` sets removed_at = NOW() instead
    of an INSERT.

ON CONFLICT pattern derived from benz-shipped-cluster-2026-07-06:
  "soft-delete re-activation pattern (ON CONFLICT + unchanged-refresh
   both must clear removed_at = NULL)"
"""

from __future__ import annotations

import logging
from typing import Any

from psycopg.types.json import Json

from parser_universal.sinks.base import EntityResult, Sink
from parser_universal.types import DomainEntity

log = logging.getLogger(__name__)


DEFAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS {table} (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    geom            JSONB,
    attrs           JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    bbox_country    TEXT,
    confidence      REAL DEFAULT 1.0,
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removed_at      TIMESTAMPTZ,
    UNIQUE (source, source_id)
);
"""


class PostgresSink:
    """Generic psycopg3 sink.

    Args:
        conn: open psycopg3 connection (use with `with psycopg.connect(...) as conn:`).
        table: target table (default: `entities`).
        soft_delete_col: column name for soft-delete (default `removed_at`).
                          Pass `None` to disable soft-delete semantics.
        on_conflict: 'DO_UPDATE' (default) / 'DO_NOTHING'.
    """

    name = "postgres"

    def __init__(
        self,
        conn: Any,  # psycopg.Connection — kept Any to avoid hard dep at import
        *,
        table: str = "entities",
        soft_delete_col: str | None = "removed_at",
        on_conflict: str = "DO_UPDATE",
    ) -> None:
        if on_conflict not in ("DO_UPDATE", "DO_NOTHING"):
            raise ValueError(f"on_conflict must be DO_UPDATE or DO_NOTHING, got {on_conflict!r}")
        self.conn = conn
        self.table = table
        self.soft_delete_col = soft_delete_col
        self.on_conflict = on_conflict

    async def upsert(self, entity: DomainEntity) -> EntityResult:
        """Idempotent UPSERT. Returns INSERTED / UPDATED / FAILED.

        Re-runs are safe: identical input → UPDATED (zero-effect on data).
        Soft-delete re-activation: passing the same entity after a previous
        remove() clears removed_at = NULL (benz durable rule).
        """
        geom = entity.geom  # (lat, lon) tuple or None
        # Sanity check on geom ordering: store as [lon, lat] JSON (GeoJSON-like)
        # to keep the door open for PostGIS swap-in. Schema column is JSONB, not
        # PostGIS geometry, so this stays portable.
        geom_payload = (
            {"type": "Point", "coordinates": [geom[1], geom[0]]} if geom else None
        )

        try:
            with self.conn.cursor() as cur:
                if self.on_conflict == "DO_NOTHING":
                    cur.execute(
                        f"""
                        INSERT INTO {self.table}
                            (source, source_id, entity_type, geom,
                             attrs, bbox_country, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source, source_id) DO NOTHING
                        RETURNING xmax = 0 AS inserted
                        """,
                        (
                            entity.source,
                            entity.source_id,
                            entity.entity_type,
                            Json(geom_payload) if geom_payload else None,
                            Json(entity.attrs),
                            entity.bbox_country,
                            entity.confidence,
                        ),
                    )
                    row = cur.fetchone()
                    return EntityResult.INSERTED if (row and row[0]) else EntityResult.SKIPPED

                # DO_UPDATE: JSONB || merge + soft-delete clear.
                cur.execute(
                    f"""
                    INSERT INTO {self.table}
                        (source, source_id, entity_type, geom,
                         attrs, bbox_country, confidence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        entity_type  = EXCLUDED.entity_type,
                        geom         = EXCLUDED.geom,
                        attrs        = {self.table}.attrs || EXCLUDED.attrs,
                        bbox_country = COALESCE(EXCLUDED.bbox_country, {self.table}.bbox_country),
                        confidence   = EXCLUDED.confidence,
                        last_seen_at = NOW()
                        {', ' + self.soft_delete_col + ' = NULL' if self.soft_delete_col else ''}
                    RETURNING (xmax = 0) AS inserted
                    """,
                    (
                        entity.source,
                        entity.source_id,
                        entity.entity_type,
                        Json(geom_payload) if geom_payload else None,
                        Json(entity.attrs),
                        entity.bbox_country,
                        entity.confidence,
                    ),
                )
                row = cur.fetchone()
                self.conn.commit()
                return EntityResult.INSERTED if (row and row[0]) else EntityResult.UPDATED
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "postgres_sink: upsert failed for %s/%s: %s",
                entity.source,
                entity.source_id,
                exc,
            )
            try:
                self.conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            return EntityResult.FAILED

    def soft_delete(self, *, source: str, source_id: str) -> bool:
        """Mark a row as removed (sets soft_delete_col = NOW()). Returns True if updated."""
        if not self.soft_delete_col:
            raise RuntimeError("this sink was created with soft_delete_col=None")
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self.table}
                SET {self.soft_delete_col} = NOW()
                WHERE source = %s AND source_id = %s
                  AND {self.soft_delete_col} IS NULL
                RETURNING 1
                """,
                (source, source_id),
            )
            row = cur.fetchone()
            self.conn.commit()
            return row is not None


__all__ = ["PostgresSink", "DEFAULT_SCHEMA"]
