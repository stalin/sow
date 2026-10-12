"""Usage contract printed by ``sow guide`` and stored on the package."""

CONTRACT = """\
Configure with [tool.sow] in pyproject.toml or SOW_DATABASE_URL. sow init writes that block and creates the seed and task directories.

Generate a module with `sow generate seed NAME` or `sow generate task NAME`.

Implement run(session) only. Async mode uses `async def run`. Leave the commit to sow. Do not call session.commit(). Do not create or alter application tables in the module.

Run `sow run` after migrations. A recorded version is skipped. sow status shows pending, recorded, and changed. `--rerun VERSION` runs one file again.

Set REPEATABLE = True only on a task that must run on every invocation.
"""
