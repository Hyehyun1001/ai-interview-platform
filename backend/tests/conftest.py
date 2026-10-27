"""공통 픽스처. 테스트마다 임시 SQLite DB 를 만들고 **Alembic 마이그레이션으로** 스키마를 생성한다 (마이그레이션 자체도 검증)."""
from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet

# app 모듈 import 전에 필수 환경변수를 주입 (개발자의 backend/.env 에 의존하지 않는다)
TEST_JWT_SECRET = "test-secret-" + "x" * 40
TEST_FERNET_KEY = Fernet.generate_key().decode()
os.environ["JWT_SECRET"] = TEST_JWT_SECRET
os.environ["DATA_ENCRYPTION_KEY"] = TEST_FERNET_KEY

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from app.core.config import BACKEND_DIR, Settings  # noqa: E402
from app.main import create_app  # noqa: E402

BASE_URL = "http://testserver"
API = "/api/v1"


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def make_settings(db_path: Path, **overrides) -> Settings:
    return Settings(
        _env_file=None, jwt_secret=TEST_JWT_SECRET, data_encryption_key=TEST_FERNET_KEY,
        database_url=f"sqlite+aiosqlite:///{db_path}", **overrides,
    )


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def migrated_db(db_url: str) -> str:
    """동기 픽스처: 이벤트 루프 밖에서 alembic upgrade head 실행."""
    command.upgrade(alembic_config(db_url), "head")
    return db_url


@pytest_asyncio.fixture
async def app(tmp_path: Path, migrated_db: str):
    application = create_app(make_settings(tmp_path / "test.db"))
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


@pytest_asyncio.fixture
async def session(app):
    async with app.state.sessionmaker() as s:
        yield s


VALID_REGISTER = {
    "name": "홍길동", "email": "Hong@Example.com", "password": "Passw0rd!", "password_confirm": "Passw0rd!",
    "birth_date": "1995/03/21", "gender": "male", "phone": "010-1234-5678",
}


@pytest.fixture
def register_payload() -> dict:
    return dict(VALID_REGISTER)


@pytest.fixture
def make_env(tmp_path: Path, migrated_db: str):
    """WebSocket 통합 테스트 환경 팩토리. 테스트가 끝나면 앱(lifespan)을 정리한다."""
    from tests.ws_env import build_env

    created = []

    def factory(**kw):  # noqa: ANN003, ANN202
        env = build_env(tmp_path, **kw)
        created.append(env)
        return env

    yield factory
    for env in created:
        env.client.__exit__(None, None, None)

pytest_plugins = ["tests.rest_env"]  # rest 픽스처 (REST 통합 테스트)
