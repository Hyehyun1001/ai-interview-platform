"""job_postings, job_questions, eval_weights, followup_rules (TRD §6.2, §6.4)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin, UTCDateTime, enum_col
from app.models.enums import JobStatus, QuestionBankStatus, QuestionSource


class JobPosting(IdMixin, TimestampMixin, Base):
    __tablename__ = "job_postings"
    __table_args__ = (
        Index("ix_job_postings_company_status_deadline", "company_id", "status", "deadline_at"),
        CheckConstraint("cutoff_score IS NULL OR (cutoff_score >= 0 AND cutoff_score <= 100)", name="cutoff_score_range"),
        CheckConstraint("cutoff_margin >= 0 AND cutoff_margin <= 20", name="cutoff_margin_range"),
        CheckConstraint("headcount IS NULL OR headcount >= 1", name="headcount_min"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_category: Mapped[str | None] = mapped_column(String(50), index=True)
    industry: Mapped[str | None] = mapped_column(String(50))
    requirements: Mapped[str | None] = mapped_column(Text)  # JD (인덱싱 대상)
    preferred: Mapped[str | None] = mapped_column(Text)
    duties: Mapped[str | None] = mapped_column(Text)
    headcount: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[JobStatus] = mapped_column(enum_col(JobStatus), default=JobStatus.DRAFT, nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    coding_test_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    coding_test_time_limit_sec: Mapped[int | None] = mapped_column(Integer)
    answer_time_limit_sec: Mapped[int | None] = mapped_column(Integer)  # 기본 답변 제한 (질문별 override 가능)
    contact_email: Mapped[str | None] = mapped_column(String(255))
    # 지원자 공고 상세에 보이는 표기용 정보 (AI 질문 생성의 JD 인덱싱 대상이 아니다)
    work_location: Mapped[str | None] = mapped_column(String(200))
    employment_type: Mapped[str | None] = mapped_column(String(20))  # regular | contract | intern | parttime
    salary_text: Mapped[str | None] = mapped_column(String(100))  # 자유 입력 ("회사 내규에 따름" 등)
    benefits: Mapped[str | None] = mapped_column(Text)
    notice: Mapped[str | None] = mapped_column(Text)  # 전형 안내·유의 사항
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_template: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    template_name: Mapped[str | None] = mapped_column(String(100))

    # AI 예상 합불 기준 (PRD 10장 #5, TRD §6.3)
    cutoff_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    cutoff_margin: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("5"), nullable=False)

    # 질문 뱅크 생성 상태 (TRD §7.6 GET .../question-bank)
    question_bank_status: Mapped[QuestionBankStatus] = mapped_column(
        enum_col(QuestionBankStatus), default=QuestionBankStatus.NONE, nullable=False
    )
    question_bank_generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    questions: Mapped[list[JobQuestion]] = relationship(back_populates="job", cascade="all, delete-orphan")
    eval_weights: Mapped[EvalWeight | None] = relationship(back_populates="job", uselist=False, cascade="all, delete-orphan")
    followup_rules: Mapped[FollowupRule | None] = relationship(back_populates="job", uselist=False, cascade="all, delete-orphan")


class JobQuestion(IdMixin, TimestampMixin, Base):
    """질문 세트(order_no 부여, 최대 10) + 질문 뱅크 후보(order_no NULL)."""

    __tablename__ = "job_questions"
    __table_args__ = (
        UniqueConstraint("job_id", "order_no", name="job_order"),
        CheckConstraint("order_no IS NULL OR (order_no >= 1 AND order_no <= 10)", name="order_no_range"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("job_postings.id", ondelete="CASCADE"), index=True, nullable=False)
    source: Mapped[QuestionSource] = mapped_column(enum_col(QuestionSource), nullable=False)
    text: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    time_limit_sec: Mapped[int | None] = mapped_column(Integer)
    order_no: Mapped[int | None] = mapped_column(Integer)

    job: Mapped[JobPosting] = relationship(back_populates="questions")


class EvalWeight(IdMixin, TimestampMixin, Base):
    __tablename__ = "eval_weights"
    __table_args__ = (
        CheckConstraint(
            "concept_understanding + logic + delivery + attitude + job_expertise + code_quality = 100", name="sum_100"
        ),
        CheckConstraint(
            "concept_understanding BETWEEN 0 AND 100 AND logic BETWEEN 0 AND 100 AND delivery BETWEEN 0 AND 100 "
            "AND attitude BETWEEN 0 AND 100 AND job_expertise BETWEEN 0 AND 100 AND code_quality BETWEEN 0 AND 100",
            name="each_0_100",
        ),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("job_postings.id", ondelete="CASCADE"), unique=True, nullable=False)
    concept_understanding: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    logic: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    delivery: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    attitude: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    job_expertise: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    code_quality: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gaze_penalty_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    job: Mapped[JobPosting] = relationship(back_populates="eval_weights")


class FollowupRule(IdMixin, TimestampMixin, Base):
    __tablename__ = "followup_rules"
    __table_args__ = (CheckConstraint("max_followups BETWEEN 1 AND 4", name="max_followups_1_4"),)

    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("job_postings.id", ondelete="CASCADE"), unique=True, nullable=False)
    max_followups: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    trigger_ambiguous: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger_contradiction: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger_stt_unclear: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    guardrail_strict: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # Grounding 필수 (기본 ON)

    job: Mapped[JobPosting] = relationship(back_populates="followup_rules")
