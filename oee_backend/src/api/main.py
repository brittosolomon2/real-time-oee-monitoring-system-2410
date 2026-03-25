import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import openapi_tags, router
from src.db.models import Base
from src.db.session import engine


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


@app.on_event("startup")
async def on_startup() -> None:
    """Create DB tables at startup (lightweight bootstrap; replace with Alembic migrations later)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/", tags=["Health"], summary="Health check")
def health_check():
    return {"message": "Healthy"}


app.include_router(router)
