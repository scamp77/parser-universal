"""FailureSink — record_failed_route equivalent for parser-universal.

Generic version of `v2.raw_routes_failed` from sup-app. Tracks failed
fetch/parse attempts with an `attempts` counter (idempotent UPSERT on
`source + source_id`) and a `failure_stage` enum.

Schema:
  CREATE TABLE IF NOT EXISTS raw_routes_failed (
      id              BIGSERIAL PRIMARY KEY,
      source          TEXT NOT NULL,
      source_id       TEXT NOT NULL,
      title           TEXT,
      url             TEXT,
      geom            JSONB,                -- main-point as {lat, lon}
      bbox_country    TEXT,
      failure_stage   TEXT NOT NULL,        -- 'fetch'|'parse'|'normalize'|'enrich'|'persist'
      failure_detail  TEXT,
      attempts        INT NOT NULL DEFAULT 1,
      first_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      UNIQUE (source, source_id)
  );
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from psycopg.types.json import Json

from parser_universal.types import RawRecord

log = logging.getLogger(__name__)


FailureStage = Literal["fetch", "parse", "normalize", "enrich", "persist"]

DEFAULT_TABLE = "raw_routes_failed"


class FailureSink:
    """Idempotent failure-recording sink (counter on `attempts`)."""

    name = "failure"

    def __init__(
        self,
        conn: Any,  # psycopg.Connection
        *,
        table: str = DEFAULT_TABLE,
    ) -> None:
        self.conn = conn
        self.table = table

    def record(
        self,
        raw: RawRecord,
        *,
        stage: FailureStage,
        detail: str,
    ) -> None:
        """Upsert a failure row. Increments attempts on conflict.

        Idempotent — calling 5 times produces 1 row with attempts=5, not 5 rows.
        """
        geom_payload = (
            {"type": "Point", "coordinates": [raw.coord_hint[1], raw.coord_hint[0]]}
            if raw.coord_hint
            else None
        )
        title = (raw.text or "")[:200] if raw.text else None
        url = raw.raw_ref if raw.raw_ref.startswith(("http://", "https://")) else None

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.table}
                        (source, source_id, title, url, geom,
                         failure_stage, failure_detail)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (source, source_id) DO UPDATE SET
                        failure_stage   = EXCLUDED.failure_stage,
                        failure_detail  = EXCLUDED.failure_detail,
                        title           = COALESCE(EXCLUDED.title, {self.table}.title),
                        url             = COALESCE(EXCLUDED.url, {self.table}.url),
                        geom            = COALESCE(EXCLUDED.geom, {self.table}.geom),
                        attempts        = {self.table}.attempts + 1,
                        last_attempt_at = NOW()
                    """,
                    (
                        raw.source,
                        raw.source_id,
                        title,
                        url,
                        Json(geom_payload) if geom_payload else None,
                        stage,
                        detail[:2000],
                    ),
                )
                self.conn.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "failure_sink: could not record %s/%s: %s",
                raw.source,
                raw.source_id,
                exc,
            )
            try:
                self.conn.rollback()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["FailureSink", "FailureStage", "DEFAULT_TABLE"]
