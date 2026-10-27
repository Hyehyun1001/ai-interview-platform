"""interview_sessions, interview_turns, voice_timeline, gaze_events, code_submissions (TRD §6.2)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, JSON, SmallInteger, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedText
from app.models.base import Base, IdMixin, TimestampMixin, UTCDateTime, enum_col
from app.models.enums import AnswerEndReason, FollowupReason, GazeKind, SessionState, TimelineKind, TurnKind, Verdict


class InterviewSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "interview_sessions"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    state: Mapped[SessionState] = mapped_column(enum_col(SessionState), default=SessionState.CREATED, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    current_turn_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    followup_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 메인 질문이 바뀌면 0
    precomputed_context: Mapped[dict | None] = mapped_column(JSON)  # 사전 검색 결과 (TRD §2.3)
    device_info: Mapped[dict | None] = mapped_column(JSON)
    stt_model: Mapped[str | None] = mapped_column(String(100))  # 재현성/감사용 기록
    llm_model: Mapped[str | None] = mapped_column(String(100))
    tts_provider: Mapped[str | None] = mapped_column(String(50))
    degraded_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    turns: Mapped[list[InterviewTurn]] = relationship(back_populates="session", cascade="all, delete-orphan", order_by="InterviewTurn.turn_no")


class InterviewTurn(IdMixin, TimestampMixin, Base):
    __tablename__ = "interview_turns"
    __table_args__ = (UniqueConstraint("session_id", "turn_no", name="session_turn"),)

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    turn_no: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[TurnKind] = mapped_column(enum_col(TurnKind), nullable=False)
    parent_turn_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("interview_turns.id", ondelete="SET NULL"))
    main_index: Mapped[int | None] = mapped_column(Integer)  # 몇 번째 메인 질문인지
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_category: Mapped[str | None] = mapped_column(String(50))
    followup_reason: Mapped[FollowupReason | None] = mapped_column(enum_col(FollowupReason))
    question_evidence: Mapped[list | None] = mapped_column(JSON)  # Evidence[] — HR 화면 "근거"
    tts_audio_path: Mapped[str | None] = mapped_column(String(500))
    asked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    answer_audio_path: Mapped[str | None] = mapped_column(String(500))  # code_followup 은 NULL (텍스트 답변)
    answer_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    answer_ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    answer_duration_ms: Mapped[int | None] = mapped_column(Integer)
    answer_text: Mapped[str | None] = mapped_column(EncryptedText)  # 🔒 STT 최종
    stt_meta: Mapped[dict | None] = mapped_column(JSON)  # 평균 logprob, no_speech_prob, 모델
    answer_end_reason: Mapped[AnswerEndReason | None] = mapped_column(enum_col(AnswerEndReason))

    session: Mapped[InterviewSession] = relationship(back_populates="turns")
    timeline: Mapped[list[VoiceTimeline]] = relationship(back_populates="turn", cascade="all, delete-orphan")
    gaze_events: Mapped[list[GazeEvent]] = relationship(back_populates="turn", cascade="all, delete-orphan")


class VoiceTimeline(IdMixin, TimestampMixin, Base):
    """음성 타임라인/하이라이트 구간 — start_ms/end_ms 는 해당 턴 오디오 기준 상대 ms (VOI-8)."""

    __tablename__ = "voice_timeline"
    __table_args__ = (
        Index("ix_voice_timeline_turn_start", "turn_id", "start_ms"),
        CheckConstraint("end_ms >= start_ms", name="range"),
        CheckConstraint("severity IS NULL OR severity BETWEEN 1 AND 3", name="severity_1_3"),
    )

    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("interview_turns.id", ondelete="CASCADE"), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[TimelineKind] = mapped_column(enum_col(TimelineKind), nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    words: Mapped[list | None] = mapped_column(JSON)  # [{w, s, e, p}]
    ai_comment: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[int | None] = mapped_column(SmallInteger)

    turn: Mapped[InterviewTurn] = relationship(back_populates="timeline")


class GazeEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "gaze_events"
    __table_args__ = (
        Index("ix_gaze_events_session_occurred", "session_id", "occurred_at"),
        Index("ix_gaze_events_turn", "turn_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), nullable=False)
    turn_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("interview_turns.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[GazeKind] = mapped_column(enum_col(GazeKind), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)  # 답변 시작 기준 상대 ms
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)  # 서버 환산 절대시각
    yaw: Mapped[float | None] = mapped_column(Float)
    pitch: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)

    turn: Mapped[InterviewTurn] = relationship(back_populates="gaze_events")


class CodeSubmission(IdMixin, TimestampMixin, Base):
    """코딩테스트 제출 (v2, Low). verdict NULL = 채점 대기."""

    __tablename__ = "code_submissions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("interview_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(20), nullable=False)
    source_code: Mapped[str] = mapped_column(EncryptedText, nullable=False)  # 🔒
    verdict: Mapped[Verdict | None] = mapped_column(enum_col(Verdict))
    case_results: Mapped[list | None] = mapped_column(JSON)
    runtime_ms: Mapped[int | None] = mapped_column(Integer)
    static_analysis: Mapped[dict | None] = mapped_column(JSON)
    ai_review: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
