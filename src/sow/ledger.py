"""Ledger table owned by sow.

Application migrations never create this table. ``ensure_ledger`` creates it
from package metadata and adds columns introduced by later package releases.
"""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
    inspect,
    text,
)
from sqlalchemy.sql.schema import Column as SchemaColumn
from sqlalchemy.sql.type_api import TypeEngine

metadata = MetaData()

sow_runs = Table(
    "sow_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("version", String(32), nullable=False),
    Column("name", String(255), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("checksum", String(64), nullable=False),
    Column(
        "ran_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    ),
    UniqueConstraint("kind", "version", name="uq_sow_runs_kind_version"),
)


def ensure_ledger(connection) -> None:
    """Create ``sow_runs`` when it is missing, then add any new columns."""
    metadata.create_all(connection, tables=[sow_runs])
    _add_missing_columns(connection)


def _add_missing_columns(connection) -> None:
    inspector = inspect(connection)
    if not inspector.has_table(sow_runs.name):
        return
    existing = {column["name"] for column in inspector.get_columns(sow_runs.name)}
    for column in sow_runs.columns:
        if column.primary_key or column.name in existing:
            continue
        connection.execute(text(_add_column_sql(column, connection.dialect)))


def _add_column_sql(column: SchemaColumn, dialect) -> str:
    preparer = dialect.identifier_preparer
    table_name = preparer.quote(sow_runs.name)
    column_name = preparer.quote(column.name)
    type_sql = column.type.compile(dialect=dialect)
    parts = [f"ALTER TABLE {table_name} ADD COLUMN {column_name} {type_sql}"]
    default_sql = _add_column_default(column)
    if default_sql is not None:
        parts.append(f"DEFAULT {default_sql}")
    if not column.nullable:
        parts.append("NOT NULL")
    return " ".join(parts)


def _add_column_default(column: SchemaColumn) -> str | None:
    """Return a constant default suitable for ``ADD COLUMN``.

    Expression defaults such as ``now()`` are omitted. SQLite rejects those
    defaults on ``ADD COLUMN``, and inserts from the runner set ``ran_at``.
    """
    server_default = column.server_default
    if server_default is not None and isinstance(server_default.arg, str):
        return server_default.arg
    if column.nullable:
        return None
    return _fallback_default(column.type)


def _fallback_default(column_type: TypeEngine) -> str:
    if isinstance(column_type, Integer):
        return "0"
    if isinstance(column_type, DateTime):
        return "'1970-01-01 00:00:00'"
    return "''"
