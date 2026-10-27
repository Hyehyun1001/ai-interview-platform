"""공통 기반: Declarative Base, UUID PK/타임스탬프 믹스인, UTC 시간 타입, Enum 컬럼 헬퍼."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import DateTime, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

# Alembic 이 제약 조건 이름을 결정적으로 생성하도록 규칙을 고정한다 (SQLite batch 변경에도 필요)
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """항상 timezone-aware UTC 로 주고받는다. SQLite 는 tz 를 저장하지 못하므로 UTC naive 로 저장 후 복원.

    naive datetime 은 의도치 않은 로컬 시간 혼입을 막기 위해 거부한다 (TRD §7: 시간은 ISO8601 UTC).
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime 은 저장할 수 없습니다 (timezone-aware UTC 사용)")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


def enum_col(enum_cls: type[enum.Enum]) -> sa.Enum:
    """VARCHAR + CHECK 제약으로 저장되는 Enum (native enum 미사용 → SQLite/PostgreSQL 동일, 값 변경 마이그레이션 용이)."""
    return sa.Enum(
        enum_cls,
        name=snake(enum_cls.__name__),
        native_enum=False,
        length=32,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
