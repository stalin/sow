"""Command line for generating and running seeds and tasks."""

from __future__ import annotations

import asyncio
import traceback
from typing import Annotated

import typer

from sow.errors import SowError
from sow.generate import generate_file
from sow.guide import CONTRACT
from sow.init import init_project
from sow.runner import Execution, Sow, format_status

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Generate and run one-shot database seeds and tasks.",
)
generate_app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Write a timestamped seed or task module.",
)
app.add_typer(generate_app, name="generate")


@app.command("guide")
def guide_command() -> None:
    """Print the steps for adding and running a seed or task."""
    typer.echo(CONTRACT.rstrip("\n"))


@app.command("init")
def init_command(
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="Database URL to write into [tool.sow]."),
    ] = None,
) -> None:
    """Write [tool.sow] and create the seed and task directories."""
    try:
        typer.echo(init_project(database_url=database_url))
    except SowError as exc:
        _fail(exc)


@generate_app.command("seed")
def generate_seed(name: Annotated[str, typer.Argument(help="Seed name")]) -> None:
    """Write a timestamped seed module."""
    _generate("seed", name)


@generate_app.command("task")
def generate_task(name: Annotated[str, typer.Argument(help="Task name")]) -> None:
    """Write a timestamped task module."""
    _generate("task", name)


@app.command("seed")
def seed_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Run one seed by name or version."),
    ] = None,
    rerun: Annotated[
        str | None,
        typer.Option("--rerun", help="Run this version again and update its ledger row."),
    ] = None,
) -> None:
    """Run pending seeds."""
    _execute(("seed",), only=name, rerun=rerun)


@app.command("task")
def task_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Run one task by name or version."),
    ] = None,
    rerun: Annotated[
        str | None,
        typer.Option("--rerun", help="Run this version again and update its ledger row."),
    ] = None,
) -> None:
    """Run pending tasks. Repeatable tasks run on every invocation."""
    _execute(("task",), only=name, rerun=rerun)


@app.command("run")
def run_command(
    rerun: Annotated[
        str | None,
        typer.Option("--rerun", help="Run this version again and update its ledger row."),
    ] = None,
) -> None:
    """Run pending seeds, then pending tasks."""
    _execute(("seed", "task"), rerun=rerun)


@app.command("status")
def status_command() -> None:
    """Show recorded, changed, and pending seeds and tasks."""
    sow = _sow()
    try:
        if sow.config.async_mode:
            entries = asyncio.run(_status(sow))
        else:
            try:
                entries = sow.status_sync()
            finally:
                sow.close()
    except SowError as exc:
        _fail(exc)
    except Exception as exc:
        _fail_unexpected(exc)
    typer.echo(format_status(entries))


def _generate(kind: str, name: str) -> None:
    sow = _sow()
    try:
        path = generate_file(
            kind=kind,
            name=name,
            directory=sow.config.seeds_dir if kind == "seed" else sow.config.tasks_dir,
            async_mode=bool(sow.config.async_mode),
        )
    except SowError as exc:
        _fail(exc)
    typer.echo(path)


def _execute(
    kinds: tuple[str, ...],
    *,
    only: str | None = None,
    rerun: str | None = None,
) -> None:
    sow = _sow()
    try:
        if sow.config.async_mode:
            ran = asyncio.run(_run(sow, kinds, only=only, rerun=rerun))
        else:
            try:
                ran = sow.run_sync(kinds=kinds, only=only, rerun=rerun)
            finally:
                sow.close()
    except SowError as exc:
        _fail(exc)
    except Exception as exc:
        _fail_unexpected(exc)
    if not ran:
        typer.echo("Nothing to run.")
        return
    for item in ran:
        typer.echo(f"{item.kind} {item.version} {item.name}")


def _sow() -> Sow:
    try:
        return Sow.from_config()
    except SowError as exc:
        _fail(exc)


async def _run(
    sow: Sow,
    kinds: tuple[str, ...],
    *,
    only: str | None,
    rerun: str | None,
) -> list[Execution]:
    try:
        return await sow.run(kinds=kinds, only=only, rerun=rerun)
    finally:
        await sow.aclose()


async def _status(sow: Sow):
    try:
        return await sow.status()
    finally:
        await sow.aclose()


def _fail(exc: SowError) -> None:
    typer.echo(str(exc), err=True)
    raise typer.Exit(code=1) from exc


def _fail_unexpected(exc: Exception) -> None:
    traceback.print_exc()
    raise typer.Exit(code=1) from exc
