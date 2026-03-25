from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Alert, AlertType, Line
from src.services.oee import OEEResult


# PUBLIC_INTERFACE
async def maybe_create_oee_alert(
    db: AsyncSession,
    *,
    line_id: int,
    run_id: Optional[int],
    shift_id: Optional[int],
    oee_result: OEEResult,
) -> Optional[Alert]:
    """
    Create an alert if OEE is below the line's target.

    Dedup behavior:
    - If a non-acknowledged OEE_BELOW_TARGET alert exists for same line+run, do not create another.
    """
    line = (await db.execute(select(Line).where(Line.id == line_id))).scalar_one_or_none()
    if not line:
        return None

    if oee_result.oee >= float(line.target_oee or 0.0):
        return None

    existing = (
        await db.execute(
            select(Alert)
            .where(Alert.line_id == line_id)
            .where(Alert.type == AlertType.OEE_BELOW_TARGET)
            .where(Alert.acknowledged_at.is_(None))
            .where(Alert.run_id == run_id)
        )
    ).scalar_one_or_none()
    if existing:
        return None

    msg = (
        f"OEE {oee_result.oee:.2%} below target {float(line.target_oee):.2%} "
        f"(A={oee_result.availability:.2%}, P={oee_result.performance:.2%}, Q={oee_result.quality:.2%})"
    )
    alert = Alert(
        line_id=line_id,
        run_id=run_id,
        shift_id=shift_id,
        type=AlertType.OEE_BELOW_TARGET,
        severity="warning",
        message=msg,
        created_at=datetime.now(timezone.utc),
        acknowledged_at=None,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert
