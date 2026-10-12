"""Create the sow directories and append ``[tool.sow]`` when it is missing."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from sow.config import resolve_config, url_is_async
from sow.errors import SowConfigError


def init_project(*, database_url: str | None = None, start: Path | None = None) -> str:
    """Append sow configuration and create the seed and task directories.

    An existing ``[tool.sow]`` table is left unchanged. The returned text is
    the message for the agent running the command.
    """
    origin = (start or Path.cwd()).resolve()
    pyproject = _find_pyproject(origin)
    url = _database_url(database_url)
    if pyproject is None:
        pyproject = origin / "pyproject.toml"
        pyproject.write_text(_tool_sow_block(url).lstrip("\n"), encoding="utf-8")
        action = "Wrote pyproject.toml."
    elif _has_tool_sow(pyproject):
        action = "[tool.sow] already exists in pyproject.toml."
    else:
        _append_tool_sow(pyproject, url)
        action = "Appended [tool.sow] to pyproject.toml."

    config = resolve_config(project_root=pyproject.parent)
    config.seeds_dir.mkdir(parents=True, exist_ok=True)
    config.tasks_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        action,
        "Next:",
        "  sow generate seed <name>",
        "  sow run",
    ]
    if config.database_url is None:
        lines.append("Set database_url in [tool.sow] or SOW_DATABASE_URL before sow run.")
    return "\n".join(lines)


def _find_pyproject(start: Path) -> Path | None:
    for candidate in [start, *start.parents]:
        path = candidate / "pyproject.toml"
        if path.is_file():
            return path
    return None


def _database_url(explicit: str | None) -> str | None:
    for value in (explicit, os.environ.get("SOW_DATABASE_URL"), os.environ.get("DATABASE_URL")):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _has_tool_sow(path: Path) -> bool:
    with path.open("rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise SowConfigError(f"{path} is not valid TOML: {exc}") from exc
    tool = data.get("tool", {})
    return isinstance(tool, dict) and "sow" in tool


def _append_tool_sow(path: Path, database_url: str | None) -> None:
    original = path.read_text(encoding="utf-8")
    block = _tool_sow_block(database_url)
    if original and not original.endswith("\n"):
        block = "\n" + block
    path.write_text(original + block, encoding="utf-8")


def _tool_sow_block(database_url: str | None) -> str:
    async_mode = True if database_url is None else url_is_async(database_url)
    lines = [
        "",
        "[tool.sow]",
        'seeds_dir = "db/seeds"',
        'tasks_dir = "db/tasks"',
    ]
    if database_url is not None:
        lines.append(f'database_url = "{_toml_string(database_url)}"')
    lines.append(f"async = {'true' if async_mode else 'false'}")
    lines.append("")
    return "\n".join(lines)


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
