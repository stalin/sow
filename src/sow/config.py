"""Resolve sow settings from arguments, the environment, and pyproject.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.engine.url import make_url

from sow.errors import SowConfigError

_ASYNC_DRIVERS = ("aiosqlite", "asyncpg", "aiomysql", "asyncmy")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class SowConfig:
    """Settings used by the generator and the runner."""

    seeds_dir: Path
    tasks_dir: Path
    database_url: str | None
    async_mode: bool | None
    project_root: Path


def resolve_config(
    *,
    seeds_dir: str | Path | None = None,
    tasks_dir: str | Path | None = None,
    database_url: str | None = None,
    async_mode: bool | None = None,
    project_root: Path | None = None,
) -> SowConfig:
    """Resolve settings.

    Each field uses the constructor argument, then its environment variable,
    then ``[tool.sow]``, then the default. ``async_mode`` stays ``None`` when
    nobody set it so the caller can detect it from the engine or the URL.
    """
    root, file_config = _load_project(project_root)
    resolved_url = _pick_str(
        database_url,
        os.environ.get("SOW_DATABASE_URL"),
        file_config.get("database_url"),
    )
    return SowConfig(
        seeds_dir=_resolve_dir(
            seeds_dir,
            os.environ.get("SOW_SEEDS_DIR"),
            file_config.get("seeds_dir"),
            "db/seeds",
            root,
        ),
        tasks_dir=_resolve_dir(
            tasks_dir,
            os.environ.get("SOW_TASKS_DIR"),
            file_config.get("tasks_dir"),
            "db/tasks",
            root,
        ),
        database_url=resolved_url,
        async_mode=_pick_bool(
            async_mode,
            os.environ.get("SOW_ASYNC"),
            file_config.get("async"),
        ),
        project_root=root,
    )


def url_is_async(database_url: str) -> bool:
    """Return whether a SQLAlchemy URL uses an async driver."""
    driver = make_url(database_url).drivername
    return any(token in driver for token in _ASYNC_DRIVERS)


def _load_project(project_root: Path | None) -> tuple[Path, dict[str, Any]]:
    if project_root is not None:
        root = project_root.resolve()
        path = root / "pyproject.toml"
        return root, _read_tool_sow(path) if path.is_file() else {}

    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        path = candidate / "pyproject.toml"
        if path.is_file():
            return candidate, _read_tool_sow(path)
    return current, {}


def _read_tool_sow(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        raise SowConfigError(f"{path} [tool] must be a table")
    sow = tool.get("sow", {})
    if not isinstance(sow, dict):
        raise SowConfigError(f"{path} [tool.sow] must be a table")
    return sow


def _pick_str(explicit: str | None, env: str | None, file_value: Any) -> str | None:
    for value in (explicit, env, file_value):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _pick_bool(explicit: bool | None, env: str | None, file_value: Any) -> bool | None:
    if explicit is not None:
        return explicit
    if env is not None and env.strip():
        return _as_bool(env, "SOW_ASYNC")
    if file_value is not None:
        return _as_bool(file_value, "[tool.sow] async")
    return None


def _as_bool(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise SowConfigError(f"{label} must be true or false, got {value!r}")


def _resolve_dir(
    explicit: str | Path | None,
    env: str | None,
    file_value: Any,
    default: str,
    root: Path,
) -> Path:
    chosen: str | Path = default
    for value in (explicit, env, file_value):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            chosen = text
            break
    path = Path(chosen)
    if not path.is_absolute():
        path = root / path
    return path.resolve()
