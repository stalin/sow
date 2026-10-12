"""Run pending seeds and tasks, recording each version in the ledger."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from sow.config import SowConfig, resolve_config, url_is_async
from sow.discover import SowModule, discover
from sow.errors import SowConfigError, SowError, SowModuleError
from sow.ledger import ensure_ledger, sow_runs


@dataclass(frozen=True)
class Execution:
    """A seed or task that ran during this invocation."""

    kind: str
    version: str
    name: str


@dataclass(frozen=True)
class StatusEntry:
    """One discovered file and its ledger state."""

    kind: str
    version: str
    name: str
    state: str
    path: Path


class Sow:
    """Generate, inspect, and run seed and task modules.

    Pass a session factory from the application, or a database URL for the CLI.
    ``prepare`` creates the ``sow_runs`` table from package metadata.
    """

    def __init__(
        self,
        *,
        seeds_dir: str | Path | None = None,
        tasks_dir: str | Path | None = None,
        database_url: str | None = None,
        async_mode: bool | None = None,
        session_factory: Any = None,
        engine: Any = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.session_factory = session_factory
        self._engine = engine
        self._owns_engine = False
        root = Path(project_root) if project_root is not None else None
        config = resolve_config(
            seeds_dir=seeds_dir,
            tasks_dir=tasks_dir,
            database_url=database_url,
            async_mode=async_mode,
            project_root=root,
        )
        self.config = self._finalize_async_mode(config)

    @classmethod
    def from_config(cls, **kwargs: Any) -> Sow:
        """Build a runner from the environment and ``pyproject.toml``."""
        return cls(**kwargs)

    async def prepare(self) -> None:
        """Create or update the ledger using the async engine."""
        self._require_async()
        engine = self._get_engine()
        async with engine.begin() as connection:
            await connection.run_sync(ensure_ledger)

    def prepare_sync(self) -> None:
        """Create or update the ledger using the sync engine."""
        self._require_sync()
        engine = self._get_engine()
        with engine.begin() as connection:
            ensure_ledger(connection)

    async def run(
        self,
        kinds: tuple[str, ...] = ("seed", "task"),
        *,
        only: str | None = None,
        rerun: str | None = None,
    ) -> list[Execution]:
        """Run pending modules of the requested kinds."""
        self._require_async()
        await self.prepare()
        return await self._run_async(kinds, only=only, rerun=rerun)

    def run_sync(
        self,
        kinds: tuple[str, ...] = ("seed", "task"),
        *,
        only: str | None = None,
        rerun: str | None = None,
    ) -> list[Execution]:
        """Run pending modules of the requested kinds with a sync session."""
        self._require_sync()
        self.prepare_sync()
        return self._run_sync(kinds, only=only, rerun=rerun)

    async def run_pending(self, kind: str) -> list[Execution]:
        """Run pending modules of one kind. Useful from a FastAPI lifespan."""
        return await self.run(kinds=(kind,))

    def run_pending_sync(self, kind: str) -> list[Execution]:
        """Run pending modules of one kind with a sync session."""
        return self.run_sync(kinds=(kind,))

    async def status(self) -> list[StatusEntry]:
        """Return recorded, changed, and pending files."""
        self._require_async()
        await self.prepare()
        recorded = {
            kind: await self._recorded_async(kind) for kind in ("seed", "task")
        }
        return _collect_status(self.config, recorded)

    def status_sync(self) -> list[StatusEntry]:
        """Return recorded, changed, and pending files using a sync session."""
        self._require_sync()
        self.prepare_sync()
        recorded = {kind: self._recorded_sync(kind) for kind in ("seed", "task")}
        return _collect_status(self.config, recorded)

    def close(self) -> None:
        """Dispose an engine this instance created."""
        if self._owns_engine and self._engine is not None and not self.config.async_mode:
            self._engine.dispose()

    async def aclose(self) -> None:
        """Dispose an async engine this instance created."""
        if self._owns_engine and self._engine is not None and self.config.async_mode:
            await self._engine.dispose()

    async def _run_async(
        self,
        kinds: tuple[str, ...],
        *,
        only: str | None,
        rerun: str | None,
    ) -> list[Execution]:
        selected = await self._select_async(kinds, only=only, rerun=rerun)
        for item in selected:
            ensure_run_matches_mode(item, async_mode=True)
        ran: list[Execution] = []
        factory = self._get_factory()
        for item in selected:
            async with factory() as session:
                async with session.begin():
                    await item.module.run(session)
                    await _apply_ledger_async(session, item)
            ran.append(Execution(item.kind, item.version, item.name))
        return ran

    def _run_sync(
        self,
        kinds: tuple[str, ...],
        *,
        only: str | None,
        rerun: str | None,
    ) -> list[Execution]:
        selected = self._select_sync(kinds, only=only, rerun=rerun)
        for item in selected:
            ensure_run_matches_mode(item, async_mode=False)
        ran: list[Execution] = []
        factory = self._get_factory()
        for item in selected:
            with factory() as session:
                with session.begin():
                    item.module.run(session)
                    _apply_ledger(session, item)
            ran.append(Execution(item.kind, item.version, item.name))
        return ran

    async def _select_async(
        self,
        kinds: tuple[str, ...],
        *,
        only: str | None,
        rerun: str | None,
    ) -> list[SowModule]:
        grouped = self._grouped(kinds, only=only, rerun=rerun)
        recorded = {kind: await self._recorded_async(kind) for kind in grouped}
        return _selected(grouped, recorded, only=only, rerun=rerun)

    def _select_sync(
        self,
        kinds: tuple[str, ...],
        *,
        only: str | None,
        rerun: str | None,
    ) -> list[SowModule]:
        grouped = self._grouped(kinds, only=only, rerun=rerun)
        recorded = {kind: self._recorded_sync(kind) for kind in grouped}
        return _selected(grouped, recorded, only=only, rerun=rerun)

    def _grouped(
        self,
        kinds: tuple[str, ...],
        *,
        only: str | None,
        rerun: str | None,
    ) -> dict[str, list[SowModule]]:
        grouped = {kind: discover(_directory(self.config, kind), kind) for kind in kinds}
        _guard_filters(grouped, only=only, rerun=rerun)
        return grouped

    async def _recorded_async(self, kind: str) -> dict[str, str]:
        factory = self._get_factory()
        async with factory() as session:
            result = await session.execute(_recorded_statement(kind))
            return {version: checksum for version, checksum in result}

    def _recorded_sync(self, kind: str) -> dict[str, str]:
        factory = self._get_factory()
        with factory() as session:
            result = session.execute(_recorded_statement(kind))
            return {version: checksum for version, checksum in result}

    def _finalize_async_mode(self, config: SowConfig) -> SowConfig:
        if config.async_mode is not None:
            return config
        if self.session_factory is not None:
            return replace(config, async_mode=factory_is_async(self.session_factory))
        if self._engine is not None:
            return replace(config, async_mode=isinstance(self._engine, AsyncEngine))
        if config.database_url:
            return replace(config, async_mode=url_is_async(config.database_url))
        return replace(config, async_mode=False)

    def _require_async(self) -> None:
        if not self.config.async_mode:
            raise SowError("This project uses sync sessions. Call the sync methods.")

    def _require_sync(self) -> None:
        if self.config.async_mode:
            raise SowError("This project uses async sessions. Call the async methods.")

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        if self.session_factory is not None:
            self._engine = bound_engine(self.session_factory)
            return self._engine
        if not self.config.database_url:
            raise SowConfigError(
                "Set database_url in [tool.sow] or SOW_DATABASE_URL, "
                "or pass an engine or session_factory."
            )
        if self.config.async_mode:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._engine = create_async_engine(self.config.database_url)
        else:
            from sqlalchemy import create_engine

            self._engine = create_engine(self.config.database_url)
        self._owns_engine = True
        return self._engine

    def _get_factory(self) -> Any:
        if self.session_factory is not None:
            return self.session_factory
        engine = self._get_engine()
        if self.config.async_mode:
            self.session_factory = async_sessionmaker(
                engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        else:
            self.session_factory = sessionmaker(
                engine,
                class_=Session,
                expire_on_commit=False,
            )
        return self.session_factory


def format_status(entries: list[StatusEntry]) -> str:
    """Render status entries for the CLI."""
    lines: list[str] = []
    for kind in ("seed", "task"):
        lines.append(f"{kind}s")
        kind_entries = [entry for entry in entries if entry.kind == kind]
        if not kind_entries:
            lines.append("  (none)")
            continue
        for entry in kind_entries:
            lines.append(f"  {entry.state:<8}  {entry.version}  {entry.name}")
    return "\n".join(lines)


def ensure_run_matches_mode(item: SowModule, *, async_mode: bool) -> None:
    """Raise before a session opens when ``run`` does not match the mode."""
    fn = getattr(item.module, "run", None)
    if not callable(fn):
        raise SowModuleError(f"{item.path} must define a run(session) function.")
    is_async = inspect.iscoroutinefunction(fn)
    if async_mode and not is_async:
        raise SowModuleError(
            f"{item.path} must define async def run(session) because sow is in async mode."
        )
    if not async_mode and is_async:
        raise SowModuleError(
            f"{item.path} must define def run(session) because sow is in sync mode."
        )


def factory_is_async(factory: Any) -> bool:
    """Return whether a session factory produces async sessions."""
    if isinstance(factory, async_sessionmaker):
        return True
    session_class = getattr(factory, "class_", None)
    return isinstance(session_class, type) and issubclass(session_class, AsyncSession)


def bound_engine(factory: Any) -> Any:
    """Return the engine bound to a session factory."""
    bind = getattr(factory, "bind", None)
    if bind is None:
        bind = getattr(factory, "kw", {}).get("bind")
    if bind is None:
        raise SowConfigError("session_factory is not bound to an engine.")
    return bind


def _directory(config: SowConfig, kind: str) -> Path:
    if kind == "seed":
        return config.seeds_dir
    if kind == "task":
        return config.tasks_dir
    raise SowError(f"Unknown kind {kind!r}. Expected 'seed' or 'task'.")


def _guard_filters(
    grouped: dict[str, list[SowModule]],
    *,
    only: str | None,
    rerun: str | None,
) -> None:
    items = [item for group in grouped.values() for item in group]
    if rerun is not None and not any(item.version == rerun for item in items):
        joined = ", ".join(grouped) or "module"
        raise SowError(f"No {joined} with version {rerun}.")
    if only is not None and not any(item.name == only or item.version == only for item in items):
        joined = ", ".join(grouped) or "module"
        raise SowError(f"No {joined} named {only}.")


def _selected(
    grouped: dict[str, list[SowModule]],
    recorded_by_kind: dict[str, dict[str, str]],
    *,
    only: str | None,
    rerun: str | None,
) -> list[SowModule]:
    selected: list[SowModule] = []
    for kind, items in grouped.items():
        recorded = recorded_by_kind.get(kind, {})
        for item in items:
            if _should_run(item, recorded, only=only, rerun=rerun):
                selected.append(item)
    return selected


def _should_run(
    item: SowModule,
    recorded: dict[str, str],
    *,
    only: str | None,
    rerun: str | None,
) -> bool:
    if only is not None and item.name != only and item.version != only:
        return False
    if rerun is not None:
        return item.version == rerun
    if item.version not in recorded:
        return True
    return item.kind == "task" and item.repeatable


def _collect_status(
    config: SowConfig,
    recorded_by_kind: dict[str, dict[str, str]],
) -> list[StatusEntry]:
    entries: list[StatusEntry] = []
    for kind in ("seed", "task"):
        recorded = recorded_by_kind.get(kind, {})
        for item in discover(_directory(config, kind), kind):
            if item.version not in recorded:
                state = "pending"
            elif recorded[item.version] != item.checksum:
                state = "changed"
            else:
                state = "recorded"
            entries.append(
                StatusEntry(
                    kind=item.kind,
                    version=item.version,
                    name=item.name,
                    state=state,
                    path=item.path,
                )
            )
    return entries


def _recorded_statement(kind: str):
    return select(sow_runs.c.version, sow_runs.c.checksum).where(sow_runs.c.kind == kind)


def _ledger_values(item: SowModule) -> dict[str, Any]:
    return {
        "name": item.name,
        "checksum": item.checksum,
        "ran_at": datetime.now(timezone.utc),
    }


def _apply_ledger(session: Session, item: SowModule) -> None:
    values = _ledger_values(item)
    existing = session.execute(_existing_statement(item)).first()
    if existing is None:
        session.execute(
            insert(sow_runs).values(version=item.version, kind=item.kind, **values)
        )
    else:
        session.execute(_update_statement(item, values))


async def _apply_ledger_async(session: AsyncSession, item: SowModule) -> None:
    values = _ledger_values(item)
    result = await session.execute(_existing_statement(item))
    if result.first() is None:
        await session.execute(
            insert(sow_runs).values(version=item.version, kind=item.kind, **values)
        )
    else:
        await session.execute(_update_statement(item, values))


def _existing_statement(item: SowModule):
    return select(sow_runs.c.version).where(
        sow_runs.c.kind == item.kind,
        sow_runs.c.version == item.version,
    )


def _update_statement(item: SowModule, values: dict[str, Any]):
    return (
        update(sow_runs)
        .where(
            sow_runs.c.kind == item.kind,
            sow_runs.c.version == item.version,
        )
        .values(**values)
    )
