"""비동기 엔진/세션 팩토리. 엔진은 앱 인스턴스(create_app)마다 생성한다 (이벤트 루프 종속 문제와 테스트 격리)."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_db(url: str) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(url, future=True)
    if engine.dialect.name == "sqlite":
        # SQLite 는 FK 가 기본 비활성이고, 단일 서버 다중 접근을 위해 WAL 이 필요하다 (TRD §1.1)
        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return engine, async_sessionmaker(engine, expire_on_commit=False)
