from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, Event, EventType, Line, Run, Shift
from src.db.session import get_db_session
from src.domain.schemas import (
    AlertAcknowledge,
    AlertOut,
    EventCreate,
    EventOut,
    LineCreate,
    LineOut,
    OEEOut,
    ReportOut,
    RunCreate,
    RunEnd,
    RunOut,
    ShiftCreate,
    ShiftOut,
)
from src.realtime.manager import ConnectionManager
from src.services.alerts import maybe_create_oee_alert
from src.services.oee import compute_oee_for_run
from src.services.reports import generate_shift_report

router = APIRouter()

openapi_tags = [
    {"name": "Lines", "description": "Manage production lines and their OEE targets."},
    {"name": "Shifts", "description": "Manage shifts per line."},
    {"name": "Runs", "description": "Manage production runs."},
    {"name": "Events", "description": "Log production/downtime/quality events."},
    {"name": "OEE", "description": "Compute OEE metrics."},
    {"name": "Alerts", "description": "Persisted alerts when OEE drops or other conditions occur."},
    {"name": "Reports", "description": "Shift handover report generation."},
    {"name": "Realtime", "description": "WebSocket endpoints for live OEE/alerts broadcasting."},
]

manager = ConnectionManager()


@router.get("/realtime", tags=["Realtime"], include_in_schema=False)
async def realtime_docs():
    """
    WebSocket usage help.

    Connect to:
    - ws://<host>/ws/oee?line_id=<line_id>

    Messages are JSON objects with a `type` field, e.g.
    - {"type":"oee_update","line_id":1,"run_id":10,"oee":{...}}
    - {"type":"alert","alert":{...}}
    """
    return {
        "websocket": "/ws/oee?line_id=<line_id>",
        "message_types": ["oee_update", "alert"],
    }


# Lines
@router.post("/lines", response_model=LineOut, tags=["Lines"], summary="Create a line")
async def create_line(payload: LineCreate, db: AsyncSession = Depends(get_db_session)):
    line = Line(name=payload.name, target_oee=payload.target_oee)
    db.add(line)
    await db.commit()
    await db.refresh(line)
    return line


@router.get("/lines", response_model=list[LineOut], tags=["Lines"], summary="List lines")
async def list_lines(db: AsyncSession = Depends(get_db_session)):
    return (await db.execute(select(Line).order_by(Line.id.asc()))).scalars().all()


# Shifts
@router.post("/shifts", response_model=ShiftOut, tags=["Shifts"], summary="Create a shift")
async def create_shift(payload: ShiftCreate, db: AsyncSession = Depends(get_db_session)):
    shift = Shift(
        line_id=payload.line_id,
        name=payload.name,
        start_ts=payload.start_ts,
        end_ts=payload.end_ts,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


@router.get("/shifts", response_model=list[ShiftOut], tags=["Shifts"], summary="List shifts")
async def list_shifts(
    line_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    q = select(Shift).order_by(Shift.start_ts.desc())
    if line_id is not None:
        q = q.where(Shift.line_id == line_id)
    return (await db.execute(q)).scalars().all()


# Runs
@router.post("/runs", response_model=RunOut, tags=["Runs"], summary="Create a run")
async def create_run(payload: RunCreate, db: AsyncSession = Depends(get_db_session)):
    run = Run(
        line_id=payload.line_id,
        shift_id=payload.shift_id,
        product_code=payload.product_code,
        ideal_cycle_time_s=payload.ideal_cycle_time_s,
        planned_production_time_s=payload.planned_production_time_s,
        started_at=payload.started_at,
        ended_at=None,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


@router.post("/runs/{run_id}/end", response_model=RunOut, tags=["Runs"], summary="End a run")
async def end_run(run_id: int, payload: RunEnd, db: AsyncSession = Depends(get_db_session)):
    run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    run.ended_at = payload.ended_at
    await db.commit()
    await db.refresh(run)
    return run


@router.get("/runs", response_model=list[RunOut], tags=["Runs"], summary="List runs")
async def list_runs(
    line_id: Optional[int] = Query(None),
    shift_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    q = select(Run).order_by(Run.started_at.desc())
    if line_id is not None:
        q = q.where(Run.line_id == line_id)
    if shift_id is not None:
        q = q.where(Run.shift_id == shift_id)
    return (await db.execute(q)).scalars().all()


# Events
@router.post("/events", response_model=EventOut, tags=["Events"], summary="Create an event and broadcast OEE/alerts")
async def create_event(payload: EventCreate, db: AsyncSession = Depends(get_db_session)):
    # Map string literal to Enum
    e_type = EventType(payload.type)
    event = Event(
        line_id=payload.line_id,
        run_id=payload.run_id,
        ts=payload.ts,
        type=e_type,
        good_count=payload.good_count,
        scrap_count=payload.scrap_count,
        downtime_reason=payload.downtime_reason,
        downtime_duration_s=payload.downtime_duration_s,
        notes=payload.notes,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    # Compute OEE for run (all events for run). Keep it simple for v1.
    run = (await db.execute(select(Run).where(Run.id == payload.run_id))).scalar_one()
    events = (
        await db.execute(
            select(Event).where(Event.run_id == payload.run_id).order_by(Event.ts.asc())
        )
    ).scalars().all()
    oee_res = compute_oee_for_run(run, events)

    # Possibly create alert
    alert = await maybe_create_oee_alert(
        db,
        line_id=run.line_id,
        run_id=run.id,
        shift_id=run.shift_id,
        oee_result=oee_res,
    )

    oee_out = OEEOut(
        availability=oee_res.availability,
        performance=oee_res.performance,
        quality=oee_res.quality,
        oee=oee_res.oee,
        good_count=oee_res.good_count,
        scrap_count=oee_res.scrap_count,
        downtime_s=oee_res.downtime_s,
        runtime_s=oee_res.runtime_s,
        planned_production_time_s=oee_res.planned_production_time_s,
    )

    # Broadcast update (best-effort)
    await manager.broadcast(
        {"type": "oee_update", "line_id": run.line_id, "run_id": run.id, "oee": oee_out.model_dump()}
    )
    if alert:
        await manager.broadcast({"type": "alert", "alert": AlertOut.model_validate(alert).model_dump()})

    return event


@router.get("/events", response_model=list[EventOut], tags=["Events"], summary="List events")
async def list_events(
    line_id: Optional[int] = Query(None),
    run_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    q = select(Event).order_by(Event.ts.desc())
    if line_id is not None:
        q = q.where(Event.line_id == line_id)
    if run_id is not None:
        q = q.where(Event.run_id == run_id)
    return (await db.execute(q)).scalars().all()


# OEE
@router.get("/oee", response_model=OEEOut, tags=["OEE"], summary="Compute OEE for a run")
async def get_oee(
    run_id: int = Query(..., description="Run ID to compute OEE for."),
    db: AsyncSession = Depends(get_db_session),
):
    run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()
    events = (await db.execute(select(Event).where(Event.run_id == run_id))).scalars().all()
    oee_res = compute_oee_for_run(run, events)
    return OEEOut(
        availability=oee_res.availability,
        performance=oee_res.performance,
        quality=oee_res.quality,
        oee=oee_res.oee,
        good_count=oee_res.good_count,
        scrap_count=oee_res.scrap_count,
        downtime_s=oee_res.downtime_s,
        runtime_s=oee_res.runtime_s,
        planned_production_time_s=oee_res.planned_production_time_s,
    )


# Alerts
@router.get("/alerts", response_model=list[AlertOut], tags=["Alerts"], summary="List alerts")
async def list_alerts(
    line_id: Optional[int] = Query(None),
    unacknowledged_only: bool = Query(False),
    db: AsyncSession = Depends(get_db_session),
):
    q = select(Alert).order_by(Alert.created_at.desc())
    if line_id is not None:
        q = q.where(Alert.line_id == line_id)
    if unacknowledged_only:
        q = q.where(Alert.acknowledged_at.is_(None))
    return (await db.execute(q)).scalars().all()


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut, tags=["Alerts"], summary="Acknowledge an alert")
async def acknowledge_alert(alert_id: int, payload: AlertAcknowledge, db: AsyncSession = Depends(get_db_session)):
    alert = (await db.execute(select(Alert).where(Alert.id == alert_id))).scalar_one()
    alert.acknowledged_at = payload.acknowledged_at
    await db.commit()
    await db.refresh(alert)
    return alert


# Reports
@router.get("/reports/shift", response_model=ReportOut, tags=["Reports"], summary="Generate a shift/window report")
async def shift_report(
    line_id: int = Query(...),
    window_start: datetime = Query(...),
    window_end: datetime = Query(...),
    shift_id: Optional[int] = Query(None),
    run_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db_session),
):
    return await generate_shift_report(
        db,
        line_id=line_id,
        shift_id=shift_id,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
    )


# WebSocket
@router.websocket("/ws/oee")
async def ws_oee(websocket: WebSocket, line_id: int = Query(..., description="Line ID to subscribe to.")):
    """
    WebSocket for live OEE updates and alerts.

    Query params:
    - line_id: which line to subscribe to (currently informational; v1 broadcasts all updates)

    Client will receive JSON messages:
    - type=oee_update
    - type=alert
    """
    await manager.connect(websocket)
    try:
        while True:
            # We don't require client messages; keep connection alive by reading.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
