from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class LineCreate(BaseModel):
    name: str = Field(..., description="Unique line name.")
    target_oee: float = Field(0.85, ge=0.0, le=1.0, description="Target OEE ratio (0..1).")


class LineOut(BaseModel):
    id: int
    name: str
    target_oee: float

    class Config:
        from_attributes = True


class ShiftCreate(BaseModel):
    line_id: int = Field(..., description="Line ID this shift belongs to.")
    name: str = Field(..., description="Shift name/label.")
    start_ts: datetime = Field(..., description="Shift start timestamp (timezone aware).")
    end_ts: datetime = Field(..., description="Shift end timestamp (timezone aware).")


class ShiftOut(BaseModel):
    id: int
    line_id: int
    name: str
    start_ts: datetime
    end_ts: datetime

    class Config:
        from_attributes = True


class RunCreate(BaseModel):
    line_id: int = Field(..., description="Line ID for the run.")
    shift_id: Optional[int] = Field(None, description="Optional shift ID.")
    product_code: Optional[str] = Field(None, description="Optional product identifier.")
    ideal_cycle_time_s: float = Field(1.0, gt=0, description="Ideal cycle time (seconds per part).")
    planned_production_time_s: Optional[int] = Field(
        None, gt=0, description="Planned production time for the run/shift in seconds."
    )
    started_at: datetime = Field(..., description="Run start timestamp (timezone aware).")


class RunEnd(BaseModel):
    ended_at: datetime = Field(..., description="Run end timestamp (timezone aware).")


class RunOut(BaseModel):
    id: int
    line_id: int
    shift_id: Optional[int]
    product_code: Optional[str]
    ideal_cycle_time_s: float
    planned_production_time_s: Optional[int]
    started_at: datetime
    ended_at: Optional[datetime]

    class Config:
        from_attributes = True


EventType = Literal["production", "downtime", "quality"]


class EventCreate(BaseModel):
    line_id: int = Field(..., description="Line ID for the event.")
    run_id: int = Field(..., description="Run ID for the event.")
    ts: datetime = Field(..., description="Event timestamp (timezone aware).")
    type: EventType = Field(..., description="Event type: production|downtime|quality.")

    good_count: Optional[int] = Field(None, ge=0, description="Good parts produced (for production/quality events).")
    scrap_count: Optional[int] = Field(None, ge=0, description="Scrap parts produced (for production/quality events).")

    downtime_reason: Optional[str] = Field(None, description="Downtime reason (for downtime events).")
    downtime_duration_s: Optional[int] = Field(None, gt=0, description="Downtime duration in seconds.")

    notes: Optional[str] = Field(None, description="Optional notes or structured payload as a string.")


class EventOut(BaseModel):
    id: int
    line_id: int
    run_id: int
    ts: datetime
    type: str

    good_count: Optional[int]
    scrap_count: Optional[int]
    downtime_reason: Optional[str]
    downtime_duration_s: Optional[int]
    notes: Optional[str]

    class Config:
        from_attributes = True


class OEEOut(BaseModel):
    availability: float = Field(..., ge=0.0, le=1.0, description="Availability ratio.")
    performance: float = Field(..., ge=0.0, le=1.0, description="Performance ratio.")
    quality: float = Field(..., ge=0.0, le=1.0, description="Quality ratio.")
    oee: float = Field(..., ge=0.0, le=1.0, description="Overall OEE ratio.")
    good_count: int = Field(..., ge=0)
    scrap_count: int = Field(..., ge=0)
    downtime_s: int = Field(..., ge=0)
    runtime_s: int = Field(..., ge=0)
    planned_production_time_s: int = Field(..., ge=0)


class AlertOut(BaseModel):
    id: int
    line_id: int
    run_id: Optional[int]
    shift_id: Optional[int]
    type: str
    severity: str
    message: str
    created_at: datetime
    acknowledged_at: Optional[datetime]

    class Config:
        from_attributes = True


class AlertAcknowledge(BaseModel):
    acknowledged_at: datetime = Field(..., description="Timestamp when the alert was acknowledged.")


class ReportOut(BaseModel):
    line_id: int
    shift_id: Optional[int]
    run_id: Optional[int]
    window_start: datetime
    window_end: datetime
    oee: OEEOut
    alerts: list[AlertOut]
    summary: str = Field(..., description="Human-readable summary suitable for shift handover.")
