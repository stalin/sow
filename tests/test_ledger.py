from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, String, Table, inspect, select, text

from sow.runner import Sow
from tests.helpers import sync_engine


def test_prepare_creates_only_the_ledger_and_restores_missing_columns(tmp_path: Path) -> None:
    engine = sync_engine()
    widgets_metadata = MetaData()
    widgets = Table(
        "widgets",
        widgets_metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    widgets_metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(widgets.insert().values(name="kept"))

    sow = Sow(
        engine=engine,
        seeds_dir=tmp_path / "seeds",
        tasks_dir=tmp_path / "tasks",
        async_mode=False,
        project_root=tmp_path,
    )
    sow.prepare_sync()
    sow.prepare_sync()

    names = set(inspect(engine).get_table_names())
    assert {"widgets", "sow_runs"} <= names
    assert names <= {"widgets", "sow_runs", "sqlite_sequence"}
    with engine.connect() as connection:
        assert connection.execute(select(widgets.c.name)).scalar_one() == "kept"

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE sow_runs DROP COLUMN name"))
    sow.prepare_sync()

    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("sow_runs")}
        assert "name" in columns
        assert connection.execute(select(widgets.c.name)).scalar_one() == "kept"
