"""Sink layer — persist DomainEntity to a destination (Postgres, SQLite, file, ...)."""

from parser_universal.sinks.base import EntityResult, Sink
from parser_universal.sinks.failure import FailureSink
from parser_universal.sinks.postgres import PostgresSink

__all__ = ["EntityResult", "Sink", "PostgresSink", "FailureSink"]
