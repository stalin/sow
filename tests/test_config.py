from pathlib import Path

import pytest

from sow.config import resolve_config
from sow.errors import SowConfigError


def test_constructor_beats_env_and_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.sow]
seeds_dir = "from-file/seeds"
tasks_dir = "from-file/tasks"
database_url = "sqlite:///file.db"
async = true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOW_SEEDS_DIR", "from-env/seeds")
    monkeypatch.setenv("SOW_TASKS_DIR", "from-env/tasks")
    monkeypatch.setenv("SOW_DATABASE_URL", "sqlite:///env.db")
    monkeypatch.setenv("SOW_ASYNC", "true")

    config = resolve_config(
        seeds_dir="from-arg/seeds",
        tasks_dir="from-arg/tasks",
        database_url="sqlite:///arg.db",
        async_mode=False,
        project_root=tmp_path,
    )

    assert config.seeds_dir == (tmp_path / "from-arg/seeds").resolve()
    assert config.tasks_dir == (tmp_path / "from-arg/tasks").resolve()
    assert config.database_url == "sqlite:///arg.db"
    assert config.async_mode is False


def test_env_beats_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.sow]
seeds_dir = "from-file/seeds"
database_url = "sqlite:///file.db"
async = true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SOW_SEEDS_DIR", "from-env/seeds")
    monkeypatch.setenv("SOW_DATABASE_URL", "sqlite+aiosqlite:///env.db")
    monkeypatch.setenv("SOW_ASYNC", "false")

    config = resolve_config(project_root=tmp_path)

    assert config.seeds_dir == (tmp_path / "from-env/seeds").resolve()
    assert config.tasks_dir == (tmp_path / "db/tasks").resolve()
    assert config.database_url == "sqlite+aiosqlite:///env.db"
    assert config.async_mode is False


def test_file_values_and_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOW_SEEDS_DIR", raising=False)
    monkeypatch.delenv("SOW_TASKS_DIR", raising=False)
    monkeypatch.delenv("SOW_DATABASE_URL", raising=False)
    monkeypatch.delenv("SOW_ASYNC", raising=False)
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.sow]
seeds_dir = "app/seeds"
tasks_dir = "app/tasks"
database_url = "postgresql+asyncpg://localhost/app"
""",
        encoding="utf-8",
    )

    config = resolve_config(project_root=tmp_path)

    assert config.seeds_dir == (tmp_path / "app/seeds").resolve()
    assert config.tasks_dir == (tmp_path / "app/tasks").resolve()
    assert config.database_url == "postgresql+asyncpg://localhost/app"
    assert config.async_mode is None


def test_explicit_root_does_not_walk_to_parent(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.sow]
seeds_dir = "from-parent/seeds"
""",
        encoding="utf-8",
    )
    child = tmp_path / "child"
    child.mkdir()

    config = resolve_config(project_root=child)

    assert config.seeds_dir == (child / "db/seeds").resolve()
    assert config.project_root == child.resolve()


def test_invalid_async_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOW_ASYNC", "maybe")

    with pytest.raises(SowConfigError, match="SOW_ASYNC"):
        resolve_config(project_root=tmp_path)
