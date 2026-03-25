from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, Event, Run
from src.domain.schemas import AlertOut, OEEOut, ReportOut
from src.services.oee import compute_oee_for_run


# PUBLIC_INTERFACE
async def generate_shift_report(
    db: AsyncSession,
    *,
    line_id: int,
    shift_id: Optional[int],
    run_id: Optional[int],
    window_start: datetime,
    window_end: datetime,
) -> ReportOut:
    """
    Generate a structured handover report for a given window.
    """
    if run_id is None:
        # Use the most recent run overlapping the window for the line.
        run = (
            await db.execute(
                select(Run)
                .where(Run.line_id == line_id)
                .where(and_(Run.started_at <= window_end, (Run.ended_at.is_(None) | (Run.ended_at >= window_start))))
                .order_by(Run.started_at.desc())
            )
        ).scalar_one_or_none()
    else:
        run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one()

    events = (
        await db.execute(
            select(Event)
            .where(Event.line_id == line_id)
            .where(Event.run_id == run.id)
            .where(Event.ts >= window_start)
            .where(Event.ts <= window_end)
            .order_by(Event.ts.asc())
        )
    ).scalars().all()

    oee_res = compute_oee_for_run(run, events, window_start=window_start, window_end=window_end)
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

    alerts = (
        await db.execute(
            select(Alert)
            .where(Alert.line_id == line_id)
            .where(Alert.created_at >= window_start)
            .where(Alert.created_at <= window_end)
            .order_by(Alert.created_at.asc())
        )
    ).scalars().all()

    alert_out = [AlertOut.model_validate(a) for a in alerts]

    summary = (
        f"Line {line_id} window {window_start.isoformat()} - {window_end.isoformat()}: "
        f"OEE {oee_out.oee:.2%} (A {oee_out.availability:.2%}, P {oee_out.performance:.2%}, Q {oee_out.quality:.2%}). "
        f"Good {oee_out.good_count}, Scrap {oee_out.scrap_count}, Downtime {oee_out.downtime_s}s. "
        f"Alerts: {len(alert_out)}."
    )

    return ReportOut(
        line_id=line_id,
        shift_id=shift_id,
        run_id=run.id,
        window_start=window_start,
        window_end=window_end,
        oee=oee_out,
        alerts=alert_out,
        summary=summary,
    )
