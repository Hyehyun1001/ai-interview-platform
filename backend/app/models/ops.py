"""schedules, notifications, job_history, jobs(잡 큐), guardrail_events, llm_audit_logs, audit_logs (TRD §6.2)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, UTCDateTime, enum_col, utcnow
from app.models.enums import QueueStatus, ScheduleType


class Schedule(IdMixin, TimestampMixin, Base):
    __tablename__ = "schedules"
    __table_args__ = (
        Index("ix_schedules_company_starts", "company_id", "starts_at"),
        CheckConstraint("ends_at IS NULL OR ends_at >= starts_at", name="range"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("job_postings.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("applications.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    type: Mapped[ScheduleType] = mapped_column(enum_col(ScheduleType), nullable=False)


class Notification(IdMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # new_application, schedule_confirmed, deadline_d1, report_ready …
    payload: Mapped[dict | None] = mapped_column(JSON)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class JobHistory(IdMixin, TimestampMixin, Base):
    """공고 작성·만료·삭제 이력 (ADM_HIS)."""

    __tablename__ = "job_history"

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("job_postings.id", ondelete="CASCADE"), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)  # created, published, closed, expired, deleted …
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))


class BackgroundJob(IdMixin, TimestampMixin, Base):
    """DB 기반 잡 큐 (OCR·인덱싱·리포트·질문 뱅크 생성). Redis/Arq 미사용 (TRD §1.1)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_at", "status", "run_at"),)

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[QueueStatus] = mapped_column(enum_col(QueueStatus), default=QueueStatus.QUEUED, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    run_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class GuardrailEvent(IdMixin, TimestampMixin, Base):
    """Guardrail 검증 실패/재시도 기록 → KPI '꼬리질문 근거 일치율' 산출 (TRD §3.5). 원문(STT/이력서)은 저장하지 않는다."""

    __tablename__ = "guardrail_events"

    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("interview_turns.id", ondelete="SET NULL"))
    chain: Mapped[str] = mapped_column(String(30), nullable=False)  # main_question | followup | report
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    check_id: Mapped[str] = mapped_column(String(10), nullable=False)  # G1 ~ G6
    reason: Mapped[str | None] = mapped_column(String(300))  # 실패 사유 요약 (≤300자, PII 금지)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # retry | fallback | passed


class LlmAuditLog(IdMixin, TimestampMixin, Base):
    """외부(Cloud) LLM 호출 감사 로그 (TRD §3.6)."""

    __tablename__ = "llm_audit_logs"

    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("interview_sessions.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pii_masked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)  # ollama_down | timeout | memory_critical


class AuditLog(IdMixin, TimestampMixin, Base):
    """담당자의 지원자 데이터 열람/다운로드/결정/메일 발송 기록 (TRD §8.3: who, what, when, ip)."""

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # view_application, play_audio, decide, send_mail, change_decision …
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    ip: Mapped[str | None] = mapped_column(String(45))
    detail: Mapped[dict | None] = mapped_column(JSON)  # 변경 전/후 값 등 (PII·원문 금지)
