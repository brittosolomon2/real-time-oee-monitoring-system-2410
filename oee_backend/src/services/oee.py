from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from src.db.models import Event, EventType, Run


@dataclass(frozen=True)
class OEEInputs:
    planned_production_time_s: int
    runtime_s: int
    downtime_s: int
    good_count: int
    scrap_count: int
    ideal_cycle_time_s: float


@dataclass(frozen=True)
class OEEResult:
    availability: float
    performance: float
    quality: float
    oee: float
    planned_production_time_s: int
    runtime_s: int
    downtime_s: int
    good_count: int
    scrap_count: int


def _safe_ratio(num: float, den: float) -> float:
    if den <= 0:
        return 0.0
    r = num / den
    return max(0.0, min(1.0, r))


def _sum_counts(events: Iterable[Event]) -> tuple[int, int]:
    good = 0
    scrap = 0
    for e in events:
        if e.type in (EventType.PRODUCTION, EventType.QUALITY):
            good += int(e.good_count or 0)
            scrap += int(e.scrap_count or 0)
    return good, scrap


def _sum_downtime(events: Iterable[Event]) -> int:
    total = 0
    for e in events:
        if e.type == EventType.DOWNTIME:
            total += int(e.downtime_duration_s or 0)
    return total


# PUBLIC_INTERFACE
def compute_oee_for_run(
    run: Run,
    events: Iterable[Event],
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
) -> OEEResult:
    """
    Compute OEE for a run (optionally limited to a time window).

    Notes:
    - Availability = runtime / planned_production_time
    - Performance = (ideal_cycle_time * total_count) / runtime
    - Quality = good / total_count
    - OEE = A * P * Q

    window_* are currently informational; events are assumed pre-filtered by caller.
    """
    planned = int(run.planned_production_time_s or 0)
    # Fallback planned time: based on run duration if ended, else 0 (caller can supply shift planned time).
    if planned <= 0 and run.ended_at and run.started_at:
        planned = int((run.ended_at - run.started_at).total_seconds())

    downtime_s = _sum_downtime(events)
    planned = max(planned, 0)
    runtime_s = max(0, planned - downtime_s)

    good, scrap = _sum_counts(events)
    total = good + scrap

    availability = _safe_ratio(runtime_s, planned)
    performance = _safe_ratio((run.ideal_cycle_time_s * total), runtime_s) if runtime_s > 0 else 0.0
    quality = _safe_ratio(good, total) if total > 0 else 0.0
    oee = max(0.0, min(1.0, availability * performance * quality))

    return OEEResult(
        availability=availability,
        performance=performance,
        quality=quality,
        oee=oee,
        planned_production_time_s=planned,
        runtime_s=runtime_s,
        downtime_s=downtime_s,
        good_count=good,
        scrap_count=scrap,
    )
