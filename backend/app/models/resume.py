"""resumes (마이페이지 등록본), resume_snapshots (지원 건별 불변 사본) — TRD §6.2."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedJSON
from app.models.base import Base, IdMixin, TimestampMixin, enum_col
from app.models.enums import ResumeSource, VectorStatus


class Resume(IdMixin, TimestampMixin, Base):
    """사용자당 최신본 1건."""

    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    source: Mapped[ResumeSource] = mapped_column(enum_col(ResumeSource), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500))  # 원본 PDF (UUID 파일명)
    data: Mapped[dict | None] = mapped_column(EncryptedJSON)  # ResumeSchema (PII 포함 🔒)
    basic_info_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ResumeSnapshot(IdMixin, TimestampMixin, Base):
    __tablename__ = "resume_snapshots"

    resume_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("resumes.id", ondelete="SET NULL"))
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    data: Mapped[dict] = mapped_column(EncryptedJSON, nullable=False)  # 지원 시점 확정본 (수정 불가)
    standard_view: Mapped[dict | None] = mapped_column(EncryptedJSON)  # 담당자용 통합 표준 템플릿 (RAG-7)
    source_file_path: Mapped[str | None] = mapped_column(String(500))
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    vector_status: Mapped[VectorStatus] = mapped_column(enum_col(VectorStatus), default=VectorStatus.PENDING, nullable=False)
