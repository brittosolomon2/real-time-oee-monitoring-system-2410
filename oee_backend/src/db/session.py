import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _build_db_url() -> str:
    """
    Build an async SQLAlchemy URL for Postgres from environment variables.

    Expected environment variables (provided by oee_database container):
    - POSTGRES_URL
    - POSTGRES_USER
    - POSTGRES_PASSWORD
    - POSTGRES_DB
    - POSTGRES_PORT
    """
    host = os.getenv("POSTGRES_URL")
    user = os.getenv("POSTGRES_USER")
    password = os.getenv("POSTGRES_PASSWORD")
    db = os.getenv("POSTGRES_DB")
    port = os.getenv("POSTGRES_PORT")

    # Do not guess defaults: fail fast so deployment agent can set .env correctly.
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
            + ". Ask orchestrator to set them in the container .env."
        )

    # POSTGRES_URL is expected to be a host (or host:port). We still prefer POSTGRES_PORT explicitly.
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
