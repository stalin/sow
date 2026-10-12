"""Source templates for generated seed and task modules."""

from __future__ import annotations


def _body(kind: str, *, async_mode: bool) -> str:
    summary = "Insert seed data." if kind == "seed" else "Run this task."
    action = "seed writes" if kind == "seed" else "task work"
    execute = (
        'await session.execute(text("INSERT INTO roles (name) VALUES (\'admin\')"))'
        if async_mode
        else 'session.execute(text("INSERT INTO roles (name) VALUES (\'admin\')"))'
    )
    return f'''\
    """{summary}

    Flush changes through session. The runner commits this work together
    with the ledger row. Do not call session.commit().
    """
    # SQLAlchemy:
    # {execute}
    #
    # SQLModel:
    # from app.models import Role
    # session.add(Role(name="admin"))
    raise NotImplementedError(
        "Replace this raise with the {action} through session. Do not call session.commit()."
    )'''


def render_module(*, kind: str, name: str, version: str, async_mode: bool) -> str:
    """Return the source for a new seed or task module."""
    title = "Seed" if kind == "seed" else "Task"
    signature = "async def run(session) -> None:" if async_mode else "def run(session) -> None:"
    lines = [
        f'"""{title}: {name}."""',
        "",
        f'VERSION = "{version}"',
        f'NAME = "{name}"',
        "",
    ]
    if kind == "task":
        lines.extend(["REPEATABLE = False", ""])
    lines.extend([signature, _body(kind, async_mode=async_mode), ""])
    return "\n".join(lines)
