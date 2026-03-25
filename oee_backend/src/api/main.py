import asyncio
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import openapi_tags, router
from src.db.models import Base
from src.db.session import engine

logger = logging.getLogger(__name__)


def _csv_env(name: str) -> list[str]:
    val = (os.getenv(name) or "").strip()
    if not val:
        return []
    return [v.strip() for v in val.split(",") if v.strip()]


app = FastAPI(
    title="Real-time OEE Monitoring API",
    description=(
        "API for logging production/downtime/quality events, computing OEE in real time, "
        "triggering alerts, generating shift handover reports, and streaming live updates over WebSocket."
    ),
    version="0.3.0",
    openapi_tags=openapi_tags,
)

# Prefer explicit allowlist from env (manifest sets these in preview), but keep permissive fallback.
allowed_origins = _csv_env("ALLOWED_ORIGINS") or ["*"]
allowed_methods = _csv_env("ALLOWED_METHODS") or ["*"]
allowed_headers = _csv_env("ALLOWED_HEADERS") or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=allowed_methods,
    allow_headers=allowed_headers,
    max_age=int(os.getenv("CORS_MAX_AGE") or "600"),
)


async def _init_db_with_retries() -> None:
    """
    Initialize DB schema with retries to tolerate database container warm-up.

    Retries are controlled by env vars (optional):
    - DB_CONNECT_RETRIES (default: 12)
    - DB_CONNECT_RETRY_DELAY_S (default: 0.5)
    - DB_CONNECT_RETRY_MAX_DELAY_S (default: 5.0)
    """
    retries = int(os.getenv("DB_CONNECT_RETRIES") or "12")
    base_delay = float(os.getenv("DB_CONNECT_RETRY_DELAY_S") or "0.5")
    max_delay = float(os.getenv("DB_CONNECT_RETRY_MAX_DELAY_S") or "5.0")

    last_err: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database connection established and schema ensured.")
            return
        except Exception as e:  # pragma: no cover (driver-specific)
            last_err = e
            if attempt >= retries:
                break

            # Gentle exponential backoff with a cap
            delay = min(max_delay, base_delay * (1.6 ** (attempt - 1)))
            logger.warning(
                "DB init/connect failed (attempt %s/%s). Retrying in %.2fs. Error: %r",
                attempt,
                retries,
                delay,
                e,
            )
            await asyncio.sleep(delay)

    # Exhausted retries
    assert last_err is not None
    raise last_err


@app.on_event("startup")
async def on_startup() -> None:
    """Create DB tables at startup (lightweight bootstrap; replace with Alembic migrations later)."""
    await _init_db_with_retries()


@app.get("/", tags=["Health"], summary="Health check")
def health_check():
    """Basic health check (process is running)."""
    return {"message": "Healthy"}


@app.get("/healthz", tags=["Health"], summary="Platform health check")
def healthz():
    """
    Health endpoint used by the platform/preview to determine service readiness.

    Note: This endpoint is intentionally lightweight and does not force a DB query;
    DB connectivity is handled during startup initialization with retries.
    """
    return {"status": "ok"}


app.include_router(router)
