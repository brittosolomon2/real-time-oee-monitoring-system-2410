from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import openapi_tags, router
from src.db.models import Base
from src.db.session import engine

app = FastAPI(
    title="Real-time OEE Monitoring API",
    description=(
        "API for logging production/downtime/quality events, computing OEE in real time, "
        "triggering alerts, generating shift handover reports, and streaming live updates over WebSocket."
    ),
    version="0.3.0",
    openapi_tags=openapi_tags,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
