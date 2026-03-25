from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class EventType(str, enum.Enum):
    """Event types supported for OEE calculations."""
    PRODUCTION = "production"  # produced good/scrap counts; optionally ideal_cycle_time
    DOWNTIME = "downtime"      # downtime reason + duration seconds
    QUALITY = "quality"        # explicit scrap/good adjustments if needed


class AlertType(str, enum.Enum):
    """Alert types emitted by the system."""
    OEE_BELOW_TARGET = "oee_below_target"


class Line(Base):
    __tablename__ = "lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    target_oee: Mapped[float] = mapped_column(Float, default=0.85)  # 0..1

    runs: Mapped[list["Run"]] = relationship(back_populates="line")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="line")


class Shift(Base):
    __tablename__ = "shifts"
    __table_args__ = (
        UniqueConstraint("line_id", "start_ts", "end_ts", name="uq_shift_line_window"),
        Index("ix_shift_line_start", "line_id", "start_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    line: Mapped["Line"] = relationship(back_populates="shifts")
    runs: Mapped[list["Run"]] = relationship(back_populates="shift")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_run_line_shift", "line_id", "shift_id"),
        Index("ix_run_active", "line_id", "ended_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"), index=True)
    shift_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shifts.id"), nullable=True)

    product_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ideal_cycle_time_s: Mapped[float] = mapped_column(Float, default=1.0)  # seconds per part
    planned_production_time_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    line: Mapped["Line"] = relationship(back_populates="runs")
    shift: Mapped[Optional["Shift"]] = relationship(back_populates="runs")
    events: Mapped[list["Event"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_event_run_ts", "run_id", "ts"),
        Index("ix_event_line_ts", "line_id", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"), index=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    type: Mapped[EventType] = mapped_column(Enum(EventType), index=True)

    # PRODUCTION
    good_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scrap_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # DOWNTIME
    downtime_reason: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    downtime_duration_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Extra payload if needed (json string for simplicity; keep deps minimal)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="events")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alert_line_ts", "line_id", "created_at"),
        Index("ix_alert_ack", "acknowledged_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("lines.id"), index=True)
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("runs.id"), nullable=True)
    shift_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shifts.id"), nullable=True)

    type: Mapped[AlertType] = mapped_column(Enum(AlertType), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="warning")  # info/warning/critical
    message: Mapped[str] = mapped_column(String(512))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Optional["Run"]] = relationship(back_populates="alerts")
