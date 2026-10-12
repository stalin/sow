import pytest


@pytest.fixture(autouse=True)
def _clear_sow_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep developer environment variables from changing resolution tests."""
    for name in ("SOW_DATABASE_URL", "SOW_SEEDS_DIR", "SOW_TASKS_DIR", "SOW_ASYNC"):
        monkeypatch.delenv(name, raising=False)
