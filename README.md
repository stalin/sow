# sow

`sow` generates timestamped seed and task modules for SQLAlchemy and SQLModel, then runs each file once. The runner records versions in a `sow_runs` table that the package creates from its own metadata.

## Quickstart

```bash
sow init
sow guide
sow generate seed roles
sow run
```

Configure with [tool.sow] in pyproject.toml or SOW_DATABASE_URL. sow init writes that block and creates the seed and task directories.

Generate a module with `sow generate seed NAME` or `sow generate task NAME`.

Implement run(session) only. Async mode uses `async def run`. Leave the commit to sow. Do not call session.commit(). Do not create or alter application tables in the module.

Run `sow run` after migrations. A recorded version is skipped. sow status shows pending, recorded, and changed. `--rerun VERSION` runs one file again.

Set REPEATABLE = True only on a task that must run on every invocation.

Fill in the generated `run` function before `sow run`. An unfilled file raises `NotImplementedError` and stays unrecorded.

Use it after your application migrations:

```bash
alembic upgrade head
sow run
```

An application without migrations uses the same `sow run`. `prepare` creates only `sow_runs`. Application tables stay under your migrations.

## Install

```bash
pip install sow
```

Install the async driver your application already uses:

```bash
pip install "sow[aiosqlite]"
pip install "sow[asyncpg]"
pip install "sow[sqlmodel]"
```

## Configure

Add this to the project `pyproject.toml`. Paths are relative to that file.

```toml
[tool.sow]
seeds_dir = "db/seeds"
tasks_dir = "db/tasks"
database_url = "sqlite+aiosqlite:///./app.db"
async = true
```

Settings resolve in this order: constructor argument, environment variable, `[tool.sow]`, then the default.

| Setting | Environment variable | Default |
| --- | --- | --- |
| `seeds_dir` | `SOW_SEEDS_DIR` | `db/seeds` |
| `tasks_dir` | `SOW_TASKS_DIR` | `db/tasks` |
| `database_url` | `SOW_DATABASE_URL` | required for the CLI |
| `async` | `SOW_ASYNC` | detected from the URL driver |

`sqlite+aiosqlite`, `postgresql+asyncpg`, and MySQL `aiomysql` / `asyncmy` URLs select async mode. A bound session factory selects the mode when you construct `Sow` in application code and omit the URL.

## Generate

```bash
sow generate seed roles
sow generate task backfill_slugs
```

Each command writes `YYYYMMDDHHMMSS_name.py` in the configured directory. Async projects get `async def run(session)`. Sync projects get `def run(session)`. Task modules include `REPEATABLE = False`.

Flush changes through the session you receive. The runner commits that work in the same transaction as the ledger row. A failure rolls both back, and the next run tries the file again.

```python
from sqlmodel import select

from app.models import Role

async def run(session) -> None:
    existing = (await session.exec(select(Role).where(Role.name == "admin"))).first()
    if existing is None:
        session.add(Role(name="admin"))
```

Set `REPEATABLE = True` on a task that should run on every `sow task` or `sow run`. The first run inserts the ledger row. Later runs execute the task again and update `ran_at` and the file checksum.

## Run

```bash
sow status
sow seed
sow task
sow run
sow seed roles
sow seed --rerun 20261012143022
```

`sow run` applies pending seeds in filename order, then pending tasks. A version already stored in `sow_runs` is skipped. `sow status` marks a recorded file whose contents changed as `changed`. That file stays skipped until you pass `--rerun` with its version.

The process exits non-zero when a module raises. Earlier files in that invocation stay recorded. The failed file has no ledger row.

## Application code

Pass the application's session factory when you want pending seeds applied on startup:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sow import Sow

sow = Sow(
    session_factory=async_session_factory,
    seeds_dir="db/seeds",
    tasks_dir="db/tasks",
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await sow.run_pending("seed")
    yield

app = FastAPI(lifespan=lifespan)
```

Sync applications call `sow.run_sync()` and `sow.run_pending_sync("seed")`.
