"""Alembic 마이그레이션 검증: 적용/롤백, 모델과 스키마의 일치(drift 없음)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.models import Base
from tests.conftest import alembic_config


def _tables(path: Path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_upgrade_creates_all_tables(migrated_db, tmp_path):
    tables = _tables(tmp_path / "test.db")
    assert set(Base.metadata.tables) <= tables
    assert "alembic_version" in tables


def test_models_and_migration_have_no_drift(migrated_db, tmp_path):
    """모델을 바꾸고 마이그레이션을 빠뜨리면 이 테스트가 실패한다."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        diff = compare_metadata(ctx, Base.metadata)
    engine.dispose()
    assert diff == [], f"모델과 마이그레이션 불일치: {diff}"


def test_downgrade_to_base_drops_everything(migrated_db, tmp_path):
    command.downgrade(alembic_config(migrated_db), "base")
    assert _tables(tmp_path / "test.db") <= {"alembic_version"}


def test_migration_is_idempotent_on_head(migrated_db):
    command.upgrade(alembic_config(migrated_db), "head")  # 재실행해도 오류 없음
