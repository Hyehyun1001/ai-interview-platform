"""Alembic 마이그레이션 검증: 적용/롤백, 모델과 스키마의 일치(drift 없음)."""
from __future__ import annotations

import asyncio

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.models import Base
from tests.conftest import alembic_config


def _run(url: str, fn):  # noqa: ANN001, ANN202  SQLite·PostgreSQL 공통: 비동기 엔진에서 동기 검사 함수를 실행
    async def go():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                return await conn.run_sync(fn)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _tables(url: str) -> set[str]:
    return _run(url, lambda c: set(inspect(c).get_table_names()))


def test_upgrade_creates_all_tables(migrated_db):
    tables = _tables(migrated_db)
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables


def test_models_and_migration_have_no_drift(migrated_db):
    """모델을 바꾸고 마이그레이션을 빠뜨리면 이 테스트가 실패한다."""
    def diff_of(conn):  # noqa: ANN001, ANN202
        return compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)

    diff = _run(migrated_db, diff_of)
    assert diff == [], f"모델과 마이그레이션 불일치: {diff}"


def test_downgrade_to_base_drops_everything(migrated_db):
    command.downgrade(alembic_config(migrated_db), "base")
    assert _tables(migrated_db) <= {"alembic_version"}


def test_migration_is_idempotent_on_head(migrated_db):
    command.upgrade(alembic_config(migrated_db), "head")  # 재실행해도 오류 없음
