"""REST API 통합 테스트 환경: 가짜 엔진/서비스를 주입한 앱 + 시드 헬퍼 (async httpx)."""
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest_asyncio

from app.ai.rag.store import VectorStore, create_chroma_client
from app.core.security import hash_password
from app.core.services import Services
from app.interview.media_store import MediaStore
from app.interview.runtime import Engines
from app.main import create_app
from app.models import Application, Company, GazeEvent, InterviewSession, InterviewTurn, JobPosting, User
from app.models.base import utcnow
from app.models.enums import (ApplicationStatus, GazeKind, JobStatus, SessionState, TurnKind, UserRole)
from tests.conftest import make_settings
from tests.fakes import FakeBrain, FakeSTT, FakeTTS, HashEmbedder, ScriptedFactory
from tests.ws_env import fast_tuning

PW = "Passw0rd!"


class Rest:
    def __init__(self, app, sm, llm: ScriptedFactory, store: VectorStore, media_root: Path):
        self.app, self.sm, self.llm, self.store, self.media_root = app, sm, llm, store, media_root

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("203.0.113.9", 50000)), base_url="http://testserver")

    async def login(self, c: httpx.AsyncClient, email: str, role: str = "applicant") -> None:
        r = await c.post("/api/v1/auth/login", json={"email": email, "password": PW, "role": role})
        assert r.status_code == 200, r.text

    async def add(self, *rows):  # noqa: ANN002, ANN201
        async with self.sm() as s:
            s.add_all(rows)
            await s.commit()

    async def company_with_recruiter(self, name="다온커머스", email="hr@corp.local") -> tuple[Company, User]:
        co = Company(name=name)
        hr = User(email=email, password_hash=hash_password(PW), role=UserRole.RECRUITER, name="담당자")
        async with self.sm() as s:
            s.add(co)
            await s.flush()
            hr.company_id = co.id
            s.add(hr)
            await s.commit()
        return co, hr

    async def applicant(self, email="a@corp.local", name="김지원") -> User:
        u = User(email=email, password_hash=hash_password(PW), role=UserRole.APPLICANT, name=name)
        await self.add(u)
        return u

    async def job(self, company_id, title="백엔드 개발자", **kw) -> JobPosting:
        j = JobPosting(company_id=company_id, title=title, status=kw.pop("status", JobStatus.OPEN), job_category=kw.pop("job_category", "개발"),
                       deadline_at=kw.pop("deadline_at", utcnow() + timedelta(days=7)), duties="주문 API 개발", requirements="Java, Redis 경험", **kw)
        await self.add(j)
        return j

    async def finished_interview(self, user: User, job: JobPosting, *, score: float | None = None, with_audio: bool = True) -> tuple[Application, InterviewSession, InterviewTurn]:
        """면접이 끝난 지원 건 (음성·시선 이벤트 포함)을 DB 에 직접 만든다."""
        app = Application(user_id=user.id, job_id=job.id, status=ApplicationStatus.INTERVIEW_DONE, consent_at=utcnow(), ai_total_score=score)
        async with self.sm() as s:
            s.add(app)
            await s.flush()
            sess = InterviewSession(application_id=app.id, state=SessionState.FINISHED, ended_at=utcnow(), started_at=utcnow())
            s.add(sess)
            await s.flush()
            turn = InterviewTurn(session_id=sess.id, turn_no=1, kind=TurnKind.MAIN, main_index=0, question_text="자기소개를 해 주세요.",
                                 answer_text="저는 백엔드 개발자입니다.", answer_duration_ms=3000)
            s.add(turn)
            await s.flush()
            s.add(GazeEvent(session_id=sess.id, turn_id=turn.id, kind=GazeKind.GAZE_AWAY, start_ms=500, end_ms=2200, occurred_at=utcnow()))
            await s.commit()
        if with_audio:
            rec = MediaStore(self.media_root).open_answer(sess.id, turn.id)
            rec.append(bytes(range(256)) * 25)  # 6,400 바이트 = 200ms
            rec.close()
        return app, sess, turn


@pytest_asyncio.fixture
async def rest(tmp_path: Path, migrated_db: str):
    llm = ScriptedFactory()
    store = VectorStore(create_chroma_client(None), HashEmbedder())
    store.client.reset()
    settings = make_settings(tmp_path / "test.db", media_root=tmp_path / "media")
    engines = Engines(stt=FakeSTT(), tts=FakeTTS(), brain=FakeBrain(total_main=2), media=MediaStore(settings.media_root), tuning=fast_tuning())
    app = create_app(settings, engines, Services(llm_factory=llm, vector_store_factory=lambda: store))
    async with app.router.lifespan_context(app):
        yield Rest(app, app.state.sessionmaker, llm, store, settings.media_root)


async def wait_until(pred, timeout=5.0):  # noqa: ANN001, ANN201
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        v = await pred()
        if v:
            return v
        await asyncio.sleep(0.02)
    raise AssertionError("timeout")


_ = uuid
