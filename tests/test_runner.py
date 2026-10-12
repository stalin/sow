from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import sessionmaker

from sow.errors import SowError
from sow.runner import Sow
from tests.helpers import async_engine, ledger_rows, note_bodies, notes, notes_metadata, sync_engine, write_module

SEED = """
from sqlalchemy import text

def run(session):
    session.execute(text("INSERT INTO notes (body) VALUES ('once')"))
"""

ASYNC_SEED = """
from sqlalchemy import text

async def run(session):
    await session.execute(text("INSERT INTO notes (body) VALUES ('once')"))
"""

FAILING_SEED = """
from sqlalchemy import text

def run(session):
    session.execute(text("INSERT INTO notes (body) VALUES ('nope')"))
    raise RuntimeError("boom")
"""

RETRY_SEED = """
from sqlalchemy import text

def run(session):
    session.execute(text("INSERT INTO notes (body) VALUES ('ok')"))
"""

REPEATABLE = """
from sqlalchemy import text

REPEATABLE = True

def run(session):
    session.execute(text("INSERT INTO notes (body) VALUES ('again')"))
"""

ORDER_SEED = """
from sqlalchemy import text

def run(session):
    session.execute(text("INSERT INTO notes (body) VALUES ('seed')"))
"""

ORDER_TASK = """
from sqlalchemy import text

def run(session):
    session.execute(text("INSERT INTO notes (body) VALUES ('task')"))
"""


def _sow(engine, tmp_path: Path, **kwargs) -> Sow:
    return Sow(
        engine=engine,
        seeds_dir=tmp_path / "seeds",
        tasks_dir=tmp_path / "tasks",
        project_root=tmp_path,
        async_mode=kwargs.get("async_mode", False),
    )


def test_non_timestamped_files_are_ignored(tmp_path: Path) -> None:
    engine = sync_engine()
    notes_metadata.create_all(engine)
    seeds = tmp_path / "seeds"
    seeds.mkdir()
    (seeds / "helpers.py").write_text(
        "def run(session):\n    raise RuntimeError('helper')\n",
        encoding="utf-8",
    )
    write_module(seeds, "20261012120000", "roles", SEED)
    sow = _sow(engine, tmp_path)

    ran = sow.run_sync(kinds=("seed",))

    assert [item.name for item in ran] == ["roles"]
    assert note_bodies(engine) == ["once"]


def test_pending_seed_runs_once(tmp_path: Path) -> None:
    engine = sync_engine()
    notes_metadata.create_all(engine)
    write_module(tmp_path / "seeds", "20261012120000", "roles", SEED)
    sow = _sow(engine, tmp_path)

    first = sow.run_sync(kinds=("seed",))
    second = sow.run_sync(kinds=("seed",))

    assert [(item.kind, item.version, item.name) for item in first] == [
        ("seed", "20261012120000", "roles")
    ]
    assert second == []
    assert note_bodies(engine) == ["once"]
    assert len(ledger_rows(engine)) == 1


def test_failed_seed_is_not_recorded_and_retries(tmp_path: Path) -> None:
    engine = sync_engine()
    notes_metadata.create_all(engine)
    path = write_module(tmp_path / "seeds", "20261012120000", "roles", FAILING_SEED)
    sow = _sow(engine, tmp_path)

    with pytest.raises(RuntimeError, match="boom"):
        sow.run_sync(kinds=("seed",))

    assert note_bodies(engine) == []
    assert ledger_rows(engine) == []

    path.write_text(RETRY_SEED.strip() + "\n", encoding="utf-8")
    ran = sow.run_sync(kinds=("seed",))

    assert [item.version for item in ran] == ["20261012120000"]
    assert note_bodies(engine) == ["ok"]
    assert len(ledger_rows(engine)) == 1


def test_repeatable_task_runs_twice_and_keeps_one_row(tmp_path: Path) -> None:
    engine = sync_engine()
    notes_metadata.create_all(engine)
    write_module(tmp_path / "tasks", "20261012130000", "backfill", REPEATABLE)
    sow = _sow(engine, tmp_path)

    sow.run_sync(kinds=("task",))
    sow.run_sync(kinds=("task",))

    assert note_bodies(engine) == ["again", "again"]
    rows = ledger_rows(engine)
    assert len(rows) == 1
    assert rows[0][0] == "task"
    assert rows[0][1] == "20261012130000"


def test_checksum_change_is_reported_and_skipped_until_rerun(tmp_path: Path) -> None:
    engine = sync_engine()
    notes_metadata.create_all(engine)
    path = write_module(tmp_path / "seeds", "20261012120000", "roles", SEED)
    sow = _sow(engine, tmp_path)
    sow.run_sync(kinds=("seed",))

    path.write_text(
        """
from sqlalchemy import text

def run(session):
    session.execute(text("INSERT INTO notes (body) VALUES ('revised')"))
""".strip()
        + "\n",
        encoding="utf-8",
    )

    status = sow.status_sync()
    assert [(entry.state, entry.version) for entry in status] == [("changed", "20261012120000")]
    assert sow.run_sync(kinds=("seed",)) == []
    assert note_bodies(engine) == ["once"]

    rerun = sow.run_sync(kinds=("seed",), rerun="20261012120000")
    assert [item.version for item in rerun] == ["20261012120000"]
    assert note_bodies(engine) == ["once", "revised"]
    assert sow.status_sync()[0].state == "recorded"
    assert len(ledger_rows(engine)) == 1


def test_run_applies_seeds_before_tasks(tmp_path: Path) -> None:
    engine = sync_engine()
    notes_metadata.create_all(engine)
    write_module(tmp_path / "tasks", "20261012100000", "earlier", ORDER_TASK)
    write_module(tmp_path / "seeds", "20261012120000", "later", ORDER_SEED)
    sow = _sow(engine, tmp_path)

    sow.run_sync()

    assert note_bodies(engine) == ["seed", "task"]


def test_sync_run_in_async_mode_fails_before_writing(tmp_path: Path) -> None:
    engine = async_engine()
    write_module(tmp_path / "seeds", "20261012120000", "roles", SEED)
    sow = _sow(engine, tmp_path, async_mode=True)

    with pytest.raises(SowError, match="async def run"):
        import asyncio

        asyncio.run(sow.run(kinds=("seed",)))


def test_async_url_selects_async_mode(tmp_path: Path) -> None:
    async_sow = Sow(database_url="sqlite+aiosqlite:///./app.db", project_root=tmp_path)
    sync_sow = Sow(database_url="sqlite:///./app.db", project_root=tmp_path)
    forced = Sow(
        database_url="sqlite+aiosqlite:///./app.db",
        async_mode=False,
        project_root=tmp_path,
    )

    assert async_sow.config.async_mode is True
    assert sync_sow.config.async_mode is False
    assert forced.config.async_mode is False


def test_session_factory_selects_async_mode(tmp_path: Path) -> None:
    engine = async_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    sow = Sow(
        session_factory=factory,
        seeds_dir=tmp_path / "seeds",
        tasks_dir=tmp_path / "tasks",
        project_root=tmp_path,
    )

    assert sow.config.async_mode is True


def test_sync_session_factory_runs_seed(tmp_path: Path) -> None:
    engine = sync_engine()
    notes_metadata.create_all(engine)
    write_module(tmp_path / "seeds", "20261012120000", "roles", SEED)
    factory = sessionmaker(engine, expire_on_commit=False)
    sow = Sow(
        session_factory=factory,
        seeds_dir=tmp_path / "seeds",
        tasks_dir=tmp_path / "tasks",
        project_root=tmp_path,
    )

    ran = sow.run_pending_sync("seed")

    assert [item.name for item in ran] == ["roles"]
    assert note_bodies(engine) == ["once"]


@pytest.mark.asyncio
async def test_async_seed_runs_once(tmp_path: Path) -> None:
    engine = async_engine()
    async with engine.begin() as connection:
        await connection.run_sync(notes_metadata.create_all)
    write_module(tmp_path / "seeds", "20261012120000", "roles", ASYNC_SEED)
    sow = _sow(engine, tmp_path, async_mode=True)

    first = await sow.run(kinds=("seed",))
    second = await sow.run(kinds=("seed",))

    assert [item.version for item in first] == ["20261012120000"]
    assert second == []
    async with engine.connect() as connection:
        result = await connection.execute(notes.select())
        bodies = [row.body for row in result]
    assert bodies == ["once"]
    await engine.dispose()
