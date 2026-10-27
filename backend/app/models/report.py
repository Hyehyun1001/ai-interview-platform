"""evaluation_reports, report_scores, highlights (TRD §6.2, §6.3)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, JSON, Numeric, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, UTCDateTime, enum_col
from app.models.enums import Criterion, HighlightKind, ReportStatus


class EvaluationReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_reports"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    status: Mapped[ReportStatus] = mapped_column(enum_col(ReportStatus), default=ReportStatus.QUEUED, nullable=False)
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # 가중 합산
    summary: Mapped[str | None] = mapped_column(Text)  # 총평
    strengths: Mapped[list | None] = mapped_column(JSON)  # [{rank, title, detail, evidence[]}]
    improvements: Mapped[list | None] = mapped_column(JSON)
    gaze_away_ratio: Mapped[float | None] = mapped_column(Float)
    weights_snapshot: Mapped[dict | None] = mapped_column(JSON)  # 생성 시점 가중치 (재현성)
    model_info: Mapped[dict | None] = mapped_column(JSON)
    generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    scores: Mapped[list[ReportScore]] = relationship(back_populates="report", cascade="all, delete-orphan")
    highlights: Mapped[list[Highlight]] = relationship(back_populates="report", cascade="all, delete-orphan")


class ReportScore(IdMixin, TimestampMixin, Base):
    __tablename__ = "report_scores"
    __table_args__ = (CheckConstraint("score >= 0 AND score <= 100", name="score_0_100"),)

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("evaluation_reports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("interview_turns.id", ondelete="CASCADE"))  # NULL = 전체
    criterion: Mapped[Criterion] = mapped_column(enum_col(Criterion), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list | None] = mapped_column(JSON)

    report: Mapped[EvaluationReport] = relationship(back_populates="scores")


class Highlight(IdMixin, TimestampMixin, Base):
    __tablename__ = "highlights"
    __table_args__ = (CheckConstraint("end_ms >= start_ms", name="range"),)

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("evaluation_reports.id", ondelete="CASCADE"), index=True, nullable=False
    )
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("interview_turns.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[HighlightKind] = mapped_column(enum_col(HighlightKind), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

    report: Mapped[EvaluationReport] = relationship(back_populates="highlights")
