"""applications, recruiter_notes (TRD §6.2)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, UTCDateTime, enum_col
from app.models.enums import AiPassPrediction, ApplicationStatus, FinalDecision


class Application(IdMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "job_id", name="user_job"),
        Index("ix_applications_job_status", "job_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_col(ApplicationStatus), default=ApplicationStatus.APPLIED, nullable=False
    )  # 진행 단계 전용. 합불은 final_decision 이 단일 출처

    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # 개인정보 동의 증적 (NFR-S5)
    consent_version: Mapped[str | None] = mapped_column()

    ai_total_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))  # 캐시 컬럼 (참고 지표)
    ai_pass_prediction: Mapped[AiPassPrediction] = mapped_column(
        enum_col(AiPassPrediction), default=AiPassPrediction.UNAVAILABLE, nullable=False
    )  # 캐시 컬럼 (산출식 TRD §6.3)

    final_decision: Mapped[FinalDecision] = mapped_column(enum_col(FinalDecision), default=FinalDecision.PENDING, nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    first_reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # POST .../reviewed 최초 호출 시각
    first_reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    result_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # 합불 안내 메일 발송 시각

    notes: Mapped[list[RecruiterNote]] = relationship(back_populates="application", cascade="all, delete-orphan")


class RecruiterNote(IdMixin, TimestampMixin, Base):
    __tablename__ = "recruiter_notes"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text, nullable=False)

    application: Mapped[Application] = relationship(back_populates="notes")
