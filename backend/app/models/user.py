"""users, companies (TRD §6.2)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedText
from app.models.base import Base, IdMixin, TimestampMixin, UTCDateTime, enum_col
from app.models.enums import UserRole


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list[User]] = relationship(back_populates="company")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)  # 소문자 정규화 저장
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # argon2id
    role: Mapped[UserRole] = mapped_column(enum_col(UserRole), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("companies.id", ondelete="SET NULL"))  # recruiter 만

    # 🔒 PII — 앱 레벨 암호화. birth_date/gender/phone 은 평가 입력에서 제외 (NFR-Q4)
    name: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    birth_date: Mapped[str | None] = mapped_column(EncryptedText)  # ISO "YYYY-MM-DD"
    gender: Mapped[str | None] = mapped_column(EncryptedText)
    phone: Mapped[str | None] = mapped_column(EncryptedText)

    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)  # 소셜 로그인 (v2)
    resume_popup_dismissed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # 가입 팝업 Skip 시각
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    company: Mapped[Company | None] = relationship(back_populates="users")
