import importlib
import sys


def _reload_session_module():
    """
    Reload src.db.session after env changes.

    session.py computes DATABASE_URL at import time, so tests must reload it
    for each scenario.
    """
    mod_name = "src.db.session"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    return importlib.import_module(mod_name)


def test_db_connection_path_parsed(monkeypatch, tmp_path):
    # Ensure env vars are absent so the code must use the file fallback.
    for k in [
        "DATABASE_URL",
        "DB_CONNECTION_URL",
        "DB_CONNECTION_PATH",
        "POSTGRES_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_PORT",
    ]:
        monkeypatch.delenv(k, raising=False)

    p = tmp_path / "db_connection.txt"
    p.write_text("psql postgresql://appuser:dbuser123@localhost:5000/myapp\n", encoding="utf-8")
    monkeypatch.setenv("DB_CONNECTION_PATH", str(p))

    session = _reload_session_module()
    assert session.DATABASE_URL == "postgresql+asyncpg://appuser:dbuser123@localhost:5000/myapp"
