import os
from pathlib import Path
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _to_asyncpg_sqlalchemy_url(url: str) -> str:
    """
    Convert a postgres URL into an async SQLAlchemy URL (asyncpg driver).

    Accepts:
    - postgresql://user:pass@host:port/db
    - postgres://user:pass@host:port/db
    - postgresql+asyncpg://... (returned as-is)
    """
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


def _read_db_url_from_connection_txt(path: Path) -> Optional[str]:
    """
    Read a Postgres URL from a db_connection.txt-style file.

    Supported formats:
    - "psql postgresql://user:pass@host:port/db"
    - "postgresql://user:pass@host:port/db"
    """
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not raw:
        return None

    # Most commonly: "psql postgresql://..."
    parts = raw.split()
    candidate = parts[-1].strip()

    if candidate.startswith(("postgresql://", "postgres://", "postgresql+asyncpg://")):
        return candidate
    return None


def _discover_db_connection_txt(start_file: Optional[Path] = None) -> Optional[Path]:
    """
    Attempt to discover db_connection.txt in common locations for preview/dev.

    This is primarily intended for Kavia preview where the repo includes:
    - oee_backend
    - oee_database (which writes db_connection.txt)

    Search order:
    1) DB_CONNECTION_PATH env var
    2) ./db_connection.txt (current working dir)
    3) <oee_backend>/db_connection.txt (relative to this file)
    4) Any real-time-oee-monitoring-system-*/oee_database/db_connection.txt while walking up parents
       (supports multi-workspace layouts where backend and database live in sibling folders)
    5) Any parent/.../oee_database/db_connection.txt while walking up

    Args:
        start_file: Optional path used as the logical location of this module when searching.
            This is intended for tests so discovery behavior can be validated without relying
            on the actual repository layout.
    """
    env_path = (os.getenv("DB_CONNECTION_PATH") or "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        return p if p.exists() else None

    candidates: list[Path] = []

    # cwd is typically container_root in preview
    candidates.append(Path.cwd() / "db_connection.txt")

    # session.py is at: <...>/oee_backend/src/db/session.py
    this_file = (start_file or Path(__file__)).resolve()
    oee_backend_dir = this_file.parents[2]
    candidates.append(oee_backend_dir / "db_connection.txt")

    # Multi-workspace layout support:
    # Walk up parents and attempt to find sibling workspaces like:
    #   <some_parent>/real-time-oee-monitoring-system-*/oee_database/db_connection.txt
    for parent in this_file.parents:
        try:
            candidates.extend(
                parent.glob("real-time-oee-monitoring-system-*/oee_database/db_connection.txt")
            )
        except OSError:
            # Ignore glob issues (permissions, etc.) and fall back to other candidates.
            pass

    # Walk up parents for a simple colocated pattern: <parent>/oee_database/db_connection.txt
    for parent in this_file.parents:
        candidates.append(parent / "oee_database" / "db_connection.txt")

    # De-duplicate while preserving order
    seen: set[str] = set()
    for p in candidates:
        ps = str(p)
        if ps in seen:
            continue
        seen.add(ps)
        if p.exists() and p.is_file():
            return p

    return None


def _build_db_url() -> str:
    """
    Build an async SQLAlchemy URL for Postgres using cross-container conventions.

    Priority:
    1) DATABASE_URL (recommended; may be copied from db_connection.txt but with async driver)
    2) DB_CONNECTION_URL (optional convenience env var that mirrors db_connection.txt URL)
    3) db_connection.txt file discovery (preview/dev convenience)
    4) POSTGRES_* environment variables (as provided by the database container)

    Notes:
    - db_connection.txt commonly contains: "psql postgresql://user:pass@host:port/db"
      This module supports using that URL without needing to duplicate host/user/pass into multiple env vars.
    """
    direct = (os.getenv("DATABASE_URL") or "").strip()
    if direct:
        return _to_asyncpg_sqlalchemy_url(direct)

    conn_url = (os.getenv("DB_CONNECTION_URL") or "").strip()
    if conn_url:
        return _to_asyncpg_sqlalchemy_url(conn_url)

    # Preview/dev fallback: discover db_connection.txt written by the DB container
    conn_txt = _discover_db_connection_txt()
    if conn_txt:
        txt_url = _read_db_url_from_connection_txt(conn_txt)
        if txt_url:
            return _to_asyncpg_sqlalchemy_url(txt_url)

    host = os.getenv("POSTGRES_URL")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    db = os.getenv("POSTGRES_DB")
    port = os.getenv("POSTGRES_PORT")

    # Allow POSTGRES_URL to be either host or full postgres URL (some platforms provide full URLs).
    if host and (host.startswith("postgres://") or host.startswith("postgresql://")):
        parsed = urlparse(host)
        # If a full URL was provided, use it, but allow POSTGRES_* to override pieces if present.
        p_user: Optional[str] = user or (parsed.username or None)
        p_pass: Optional[str] = password or (parsed.password or None)
        p_host: Optional[str] = parsed.hostname or None
        p_port: Optional[int] = int(port) if port else (parsed.port or None)
        p_db: Optional[str] = db or (parsed.path.lstrip("/") or None)

        missing = [
            k
            for k, v in {
                "POSTGRES_USER": p_user,
                "POSTGRES_PASSWORD": p_pass,
                "POSTGRES_URL(host)": p_host,
                "POSTGRES_PORT": p_port,
                "POSTGRES_DB": p_db,
            }.items()
            if not v
        ]
        if missing:
            raise RuntimeError(
                "Missing required DB settings: "
                + ", ".join(missing)
                + ". Provide DATABASE_URL (preferred), DB_CONNECTION_URL, "
                + "DB_CONNECTION_PATH, or set POSTGRES_* env vars."
            )
        return f"postgresql+asyncpg://{p_user}:{p_pass}@{p_host}:{p_port}/{p_db}"

    # Classic split vars case: POSTGRES_URL is expected to be a host (or host:port).
    missing = [
        k
        for k, v in {
            "POSTGRES_URL": host,
            "POSTGRES_USER": user,
            "POSTGRES_PASSWORD": password,
            "POSTGRES_DB": db,
            "POSTGRES_PORT": port,
        }.items()
        if not v
    ]
    if missing:
        raise RuntimeError(
            "Missing required DB settings: "
            + ", ".join(missing)
            + ". Provide DATABASE_URL (preferred), DB_CONNECTION_URL, "
            + "DB_CONNECTION_PATH (pointing to db_connection.txt), or set POSTGRES_* env vars."
        )

    host_only = host.split(":")[0]
    return f"postgresql+asyncpg://{user}:{password}@{host_only}:{port}/{db}"


DATABASE_URL = _build_db_url()

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


# PUBLIC_INTERFACE
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async SQLAlchemy session."""
    async with AsyncSessionLocal() as session:
        yield session
