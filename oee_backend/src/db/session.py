import os
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


def _build_db_url() -> str:
    """
    Build an async SQLAlchemy URL for Postgres using cross-container conventions.

    Priority:
    1) DATABASE_URL (recommended; may be copied from db_connection.txt but with async driver)
    2) POSTGRES_* environment variables (as provided by the database container)
    3) DB_CONNECTION_URL (optional convenience env var that mirrors db_connection.txt)

    Notes:
    - db_connection.txt commonly contains: psql postgresql://user:pass@host:port/db
      This module supports using that URL via DATABASE_URL/DB_CONNECTION_URL without needing to
      duplicate host/user/pass into multiple env vars.
    """
    direct = (os.getenv("DATABASE_URL") or "").strip()
    if direct:
        return _to_asyncpg_sqlalchemy_url(direct)

    conn_url = (os.getenv("DB_CONNECTION_URL") or "").strip()
    if conn_url:
        return _to_asyncpg_sqlalchemy_url(conn_url)

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

        missing = [k for k, v in {
            "POSTGRES_USER": p_user,
            "POSTGRES_PASSWORD": p_pass,
            "POSTGRES_URL(host)": p_host,
            "POSTGRES_PORT": p_port,
            "POSTGRES_DB": p_db,
        }.items() if not v]
        if missing:
            raise RuntimeError(
                "Missing required DB settings: "
                + ", ".join(missing)
                + ". Provide DATABASE_URL (preferred) or set POSTGRES_* env vars."
            )
        return f"postgresql+asyncpg://{p_user}:{p_pass}@{p_host}:{p_port}/{p_db}"

    # Classic split vars case: POSTGRES_URL is expected to be a host (or host:port).
    missing = [k for k, v in {
        "POSTGRES_URL": host,
        "POSTGRES_USER": user,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": db,
        "POSTGRES_PORT": port,
    }.items() if not v]
    if missing:
        raise RuntimeError(
            "Missing required DB env vars: "
            + ", ".join(missing)
            + ". Provide DATABASE_URL (preferred; can be derived from db_connection.txt) "
              "or ask orchestrator to set POSTGRES_* env vars in the container .env."
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
