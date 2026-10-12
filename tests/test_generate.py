from datetime import datetime, timezone
from pathlib import Path

import pytest

from sow.errors import SowError
from sow.generate import generate_file


def test_generate_writes_timestamped_seed(tmp_path: Path) -> None:
    directory = tmp_path / "custom" / "seeds"
    path = generate_file(
        kind="seed",
        name="Admin User",
        directory=directory,
        async_mode=True,
        now=datetime(2026, 10, 12, 14, 30, 22, tzinfo=timezone.utc),
    )

    assert path == directory / "20261012143022_admin_user.py"
    source = path.read_text(encoding="utf-8")
    assert 'VERSION = "20261012143022"' in source
    assert "async def run(session)" in source
    assert "NotImplementedError" in source
    assert "Do not call session.commit()" in source
    assert "await session.execute" in source


def test_generate_task_is_sync_and_not_repeatable(tmp_path: Path) -> None:
    path = generate_file(
        kind="task",
        name="Backfill-Slugs",
        directory=tmp_path / "tasks",
        async_mode=False,
        now=datetime(2026, 10, 12, 15, 0, 0, tzinfo=timezone.utc),
    )

    source = path.read_text(encoding="utf-8")
    assert path.name == "20261012150000_backfill_slugs.py"
    assert "REPEATABLE = False" in source
    assert "def run(session)" in source
    assert "async def run" not in source
    assert "NotImplementedError" in source
    assert "session.execute" in source


def test_generate_rejects_blank_name(tmp_path: Path) -> None:
    with pytest.raises(SowError, match="Invalid name"):
        generate_file(
            kind="seed",
            name="???",
            directory=tmp_path,
            async_mode=False,
        )
