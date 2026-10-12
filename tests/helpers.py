"""Shared fixtures for sow tests."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from sow.ledger import sow_runs

notes_metadata = MetaData()
notes = Table(
    "notes",
    notes_metadata,
    Column("id", Integer, primary_key=True),
    Column("body", String, nullable=False),
)


def sync_engine():
    """Return an in-memory SQLite engine shared across connections."""
    return create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def async_engine():
    """Return an in-memory async SQLite engine shared across connections."""
    return create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def write_module(directory: Path, version: str, name: str, source: str) -> Path:
    """Write a timestamped module and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{version}_{name}.py"
    path.write_text(source.strip() + "\n", encoding="utf-8")
    return path


def note_bodies(engine) -> list[str]:
    """Return note bodies in insert order."""
    with engine.connect() as connection:
        rows = connection.execute(select(notes.c.body).order_by(notes.c.id)).all()
    return [row[0] for row in rows]


def ledger_rows(engine) -> list[tuple[str, str, str]]:
    """Return ``(kind, version, checksum)`` rows from the ledger."""
    with engine.connect() as connection:
        rows = connection.execute(
            select(sow_runs.c.kind, sow_runs.c.version, sow_runs.c.checksum).order_by(
                sow_runs.c.kind,
                sow_runs.c.version,
            )
        ).all()
    return [(row[0], row[1], row[2]) for row in rows]
