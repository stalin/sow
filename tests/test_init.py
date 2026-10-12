from pathlib import Path

import sow
from sow.guide import CONTRACT
from sow.init import init_project


def test_package_doc_and_readme_use_the_contract() -> None:
    readme = Path(__file__).resolve().parents[1].joinpath("README.md").read_text(encoding="utf-8")

    assert sow.__doc__ == CONTRACT
    assert CONTRACT in readme
    assert "sow generate seed" in CONTRACT
    assert "session.commit()" in CONTRACT


def test_init_appends_config_once(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\n',
        encoding="utf-8",
    )
    database_url = f"sqlite:///{(tmp_path / 'app.db').as_posix()}"

    first = init_project(database_url=database_url, start=tmp_path)
    written = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    assert written.count("[tool.sow]") == 1
    assert '[project]\nname = "app"\n' in written
    assert 'seeds_dir = "db/seeds"' in written
    assert 'tasks_dir = "db/tasks"' in written
    assert f'database_url = "{database_url}"' in written
    assert "async = false" in written
    assert (tmp_path / "db" / "seeds").is_dir()
    assert (tmp_path / "db" / "tasks").is_dir()
    assert "sow generate seed <name>" in first
    assert "sow run" in first

    second = init_project(database_url=database_url, start=tmp_path)

    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == written
    assert "already exists" in second


def test_init_without_url_stays_async_and_says_how_to_set_it(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "app"\n',
        encoding="utf-8",
    )

    message = init_project(start=tmp_path)
    written = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")

    assert "async = true" in written
    assert "database_url" not in written
    assert "SOW_DATABASE_URL" in message
