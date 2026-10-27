"""Alembic 비동기 환경. DB URL 우선순위: alembic -x url=... > config sqlalchemy.url > Settings(DATABASE_URL)."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (모든 모델을 Base.metadata 에 등록)
from app.core.crypto import EncryptedJSON, EncryptedText
from app.models.base import Base, UTCDateTime

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_url() -> str:
    x = context.get_x_argument(as_dictionary=True)
    if "url" in x:
        return x["url"]
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    from app.core.config import DatabaseSettings

    return DatabaseSettings().database_url  # 비밀키 없이도 동작 (DATABASE_URL 환경변수/.env 또는 기본 dev.db)


def render_item(type_: str, obj, autogen_context):  # noqa: ANN001, ANN201
    """마이그레이션 파일이 앱 코드(TypeDecorator)에 의존하지 않도록 저장 타입(impl)으로 렌더링한다."""
    if type_ == "type":
        if isinstance(obj, (EncryptedText, EncryptedJSON)):
            return "sa.Text()"
        if isinstance(obj, UTCDateTime):
            return "sa.DateTime(timezone=True)"
    return False


def _configure(**kw) -> None:  # noqa: ANN003
    context.configure(
        target_metadata=target_metadata, compare_type=True, render_item=render_item,
        render_as_batch=kw.pop("is_sqlite", False), **kw,
    )


def run_migrations_offline() -> None:
    url = get_url()
    _configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"}, is_sqlite=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    _configure(connection=connection, is_sqlite=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(get_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
