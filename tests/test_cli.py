from pathlib import Path

from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from sow.cli import app
from tests.helpers import notes_metadata

runner = CliRunner()


def _project(tmp_path: Path, *, async_mode: bool) -> None:
    database = tmp_path / "app.db"
    flag = "true" if async_mode else "false"
    (tmp_path / "pyproject.toml").write_text(
        f"""
[tool.sow]
seeds_dir = "db/seeds"
tasks_dir = "db/tasks"
database_url = "sqlite:///{database.as_posix()}"
async = {flag}
""",
        encoding="utf-8",
    )


def test_cli_unfilled_seed_is_not_recorded_until_it_inserts(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, async_mode=False)

    generated = runner.invoke(app, ["generate", "seed", "roles"])
    assert generated.exit_code == 0, generated.output
    path = next((tmp_path / "db" / "seeds").glob("*.py"))
    assert "def run(session)" in path.read_text(encoding="utf-8")

    unfilled = runner.invoke(app, ["seed"])
    assert unfilled.exit_code == 1, unfilled.output
    assert "NotImplementedError" in unfilled.output
    assert "session.commit()" in unfilled.output

    pending = runner.invoke(app, ["status"])
    assert pending.exit_code == 0, pending.output
    assert "pending" in pending.stdout
    assert "recorded" not in pending.stdout

    _fill_seed(path)
    engine = create_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    notes_metadata.create_all(engine)
    engine.dispose()

    first = runner.invoke(app, ["seed"])
    assert first.exit_code == 0, first.output
    assert "seed " in first.stdout

    status = runner.invoke(app, ["status"])
    assert status.exit_code == 0, status.output
    assert "recorded" in status.stdout

    second = runner.invoke(app, ["seed"])
    assert second.exit_code == 0, second.output
    assert "Nothing to run." in second.stdout

    recorded = create_engine(f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    with recorded.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM sow_runs")).scalar_one()
        body = connection.execute(text("SELECT body FROM notes")).scalar_one()
    recorded.dispose()
    assert count == 1
    assert body == "ok"


def _fill_seed(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    start = source.index("    raise NotImplementedError(")
    filled = source[:start] + "    session.execute(text(\"INSERT INTO notes (body) VALUES ('ok')\"))\n"
    if "from sqlalchemy import text" not in filled:
        filled = "from sqlalchemy import text\n\n" + filled
    path.write_text(filled, encoding="utf-8")


def test_cli_generate_async_task_template(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _project(tmp_path, async_mode=True)

    generated = runner.invoke(app, ["generate", "task", "backfill slugs"])
    assert generated.exit_code == 0, generated.output
    source = next((tmp_path / "db" / "tasks").glob("*.py")).read_text(encoding="utf-8")
    assert "async def run(session)" in source
    assert "REPEATABLE = False" in source


def test_cli_guide_prints_the_contract(tmp_path: Path, monkeypatch) -> None:
    result = runner.invoke(app, ["guide"])

    assert result.exit_code == 0, result.output
    assert "sow generate seed" in result.stdout
    assert "sow generate task" in result.stdout
    assert "session.commit()" in result.stdout


def test_cli_init_appends_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\n',
        encoding="utf-8",
    )
    database_url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"

    first = runner.invoke(app, ["init", "--database-url", database_url])
    assert first.exit_code == 0, first.output
    written = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert written.count("[tool.sow]") == 1
    assert (tmp_path / "db" / "seeds").is_dir()
    assert (tmp_path / "db" / "tasks").is_dir()
    assert "sow generate seed <name>" in first.stdout

    second = runner.invoke(app, ["init", "--database-url", database_url])
    assert second.exit_code == 0, second.output
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == written


def test_cli_missing_database_url(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SOW_DATABASE_URL", raising=False)
    (tmp_path / "pyproject.toml").write_text("[tool.sow]\nasync = false\n", encoding="utf-8")

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "database_url" in result.output
