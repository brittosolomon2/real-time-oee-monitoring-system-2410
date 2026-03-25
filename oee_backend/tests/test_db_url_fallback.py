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


def test_discover_db_connection_searches_parent_workspaces(monkeypatch, tmp_path):
    """
    Validate that discovery can find db_connection.txt in a sibling workspace layout.

    This mirrors preview setups where multiple workspaces live under a shared parent
    directory (e.g., /.../code-generation/real-time-oee-monitoring-system-2408/...).
    """
    # Import module successfully using explicit path override first (so import-time URL build works).
    bootstrap = tmp_path / "bootstrap_db_connection.txt"
    bootstrap.write_text("psql postgresql://u:p@localhost:5000/db\n", encoding="utf-8")
    monkeypatch.setenv("DB_CONNECTION_PATH", str(bootstrap))
    session = _reload_session_module()

    # Unset so _discover_db_connection_txt doesn't short-circuit to the bootstrap file.
    monkeypatch.delenv("DB_CONNECTION_PATH", raising=False)

    workspace_root = tmp_path / "code-generation"
    db_conn = (
        workspace_root
        / "real-time-oee-monitoring-system-2408"
        / "oee_database"
        / "db_connection.txt"
    )
    db_conn.parent.mkdir(parents=True, exist_ok=True)
    db_conn.write_text("psql postgresql://u2:p2@localhost:5000/db2\n", encoding="utf-8")

    fake_this_file = (
        workspace_root
        / "real-time-oee-monitoring-system-2410"
        / "oee_backend"
        / "src"
        / "db"
        / "session.py"
    )
    fake_this_file.parent.mkdir(parents=True, exist_ok=True)
    fake_this_file.write_text("# test sentinel\n", encoding="utf-8")

    discovered = session._discover_db_connection_txt(start_file=fake_this_file)
    assert discovered == db_conn
