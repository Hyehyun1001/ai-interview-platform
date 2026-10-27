"""WebSocket 통합 테스트 환경: 실제 앱 + Alembic 으로 만든 DB + 가짜 엔진(STT/TTS/두뇌). 타이밍은 즉시 진행되도록 줄인다."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from starlette.testclient import TestClient, WebSocketDisconnect

from app.core.database import create_db
from app.core.security import hash_password
from app.interview import protocol
from app.interview.media_store import MediaStore
from app.interview.runtime import Engines, Tuning
from app.main import create_app
from app.models import Application, Company, FollowupRule, InterviewSession, InterviewTurn, JobPosting, User
from app.models.enums import ApplicationStatus, SessionState, UserRole
from tests.conftest import make_settings
from tests.fakes import FakeBrain, FakeSTT, FakeTTS

PASSWORD = "Passw0rd!"


async def _instant(_seconds: float) -> None:
    await asyncio.sleep(0)


def fast_tuning(**kw: Any) -> Tuning:
    base = dict(countdown_sleep=_instant, tts_done_timeout_s=10.0, tts_fail_grace_s=0.05, answer_start_grace_s=0.3,
                reconnect_grace_s=30.0, pause_ttl_s=1800.0, silence_end_ms=2000, min_answer_ms=1000, max_reasks=2,
                timeout_scale=1.0, ping_interval_s=15.0)
    return Tuning(**{**base, **kw})


@dataclass
class Env:
    app: Any
    client: TestClient
    settings: Any
    engines: Engines
    brain: FakeBrain
    stt: FakeSTT
    tts: FakeTTS
    media_root: Path
    session_id: uuid.UUID
    application_id: uuid.UUID
    user_id: uuid.UUID
    job_id: uuid.UUID
    company_id: uuid.UUID
    email: str = "applicant@corp.local"
    extra: dict = field(default_factory=dict)

    def login(self, email: str | None = None, password: str = PASSWORD) -> None:
        r = self.client.post("/api/v1/auth/login", json={"email": email or self.email, "password": password, "role": "applicant"})
        assert r.status_code == 200, r.text

    def tokens(self, session_id: uuid.UUID | None = None) -> dict[str, str]:
        r = self.client.post(f"/api/v1/sessions/{session_id or self.session_id}/ws-token")
        assert r.status_code == 200, r.text
        return r.json()

    def control(self, token: str | None = None, session_id: uuid.UUID | None = None):  # noqa: ANN201
        sid = session_id or self.session_id
        token = token if token is not None else self.tokens(sid)["control_token"]
        return self.client.websocket_connect(f"/ws/sessions/{sid}/control?token={token}")

    def media(self, token: str | None = None, session_id: uuid.UUID | None = None):  # noqa: ANN201
        sid = session_id or self.session_id
        token = token if token is not None else self.tokens(sid)["media_token"]
        return self.client.websocket_connect(f"/ws/sessions/{sid}/media?token={token}")

    def db(self, coro_fn):  # noqa: ANN001, ANN201
        """앱과 같은 DB 를 별도 이벤트 루프에서 조회/수정한다 (TestClient 가 앱 루프를 점유하므로)."""
        async def run():  # noqa: ANN202
            engine, sm = create_db(self.settings.database_url)
            try:
                async with sm() as s:
                    return await coro_fn(s)
            finally:
                await engine.dispose()

        return asyncio.run(run())

    def turns(self) -> list[InterviewTurn]:
        return self.db(lambda s: _all(s, select(InterviewTurn).where(InterviewTurn.session_id == self.session_id)
                                      .order_by(InterviewTurn.turn_no)))

    def session_row(self) -> InterviewSession:
        return self.db(lambda s: s.get(InterviewSession, self.session_id))

    def state_json(self) -> dict:
        return self.client.get(f"/api/v1/sessions/{self.session_id}/state").json()

    def wait_for(self, predicate, timeout: float = 5.0, what: str = "condition"):  # noqa: ANN001, ANN201
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        raise AssertionError(f"timeout waiting for {what}")


async def _all(s, stmt):  # noqa: ANN001, ANN202
    return (await s.execute(stmt)).scalars().all()


async def _seed(url: str, *, state: SessionState, slots: int, max_followups: int, coding: bool, extra_sessions: int) -> dict:
    engine, sm = create_db(url)
    out: dict[str, Any] = {"extra_sessions": []}
    async with sm() as s:
        company = Company(name="다온커머스")
        s.add(company)
        await s.flush()
        user = User(email="applicant@corp.local", password_hash=hash_password(PASSWORD), role=UserRole.APPLICANT, name="김지원")
        other = User(email="other@corp.local", password_hash=hash_password(PASSWORD), role=UserRole.APPLICANT, name="이다른")
        recruiter = User(email="hr@corp.local", password_hash=hash_password(PASSWORD), role=UserRole.RECRUITER,
                         company_id=company.id, name="담당자")
        s.add_all([user, other, recruiter])
        job = JobPosting(company_id=company.id, title="백엔드 개발자", status="open", answer_time_limit_sec=60,
                         coding_test_enabled=coding, coding_test_time_limit_sec=3600 if coding else None)
        s.add(job)
        await s.flush()
        s.add(FollowupRule(job_id=job.id, max_followups=max_followups))

        async def session_for(u: User, st: SessionState) -> tuple[Application, InterviewSession]:
            app_ = Application(user_id=u.id, job_id=job.id, status=ApplicationStatus.PREPARED)
            s.add(app_)
            await s.flush()
            sess = InterviewSession(application_id=app_.id, state=st, precomputed_context={"slots": [{} for _ in range(slots)]})
            s.add(sess)
            await s.flush()
            return app_, sess

        app_, sess = await session_for(user, state)
        out.update(session_id=sess.id, application_id=app_.id, user_id=user.id, job_id=job.id, company_id=company.id,
                   other_user_id=other.id, recruiter_id=recruiter.id)
        for _ in range(extra_sessions):  # 동시 세션 한도 테스트용 (다른 지원자)
            o_app, o_sess = await session_for(other, SessionState.READY)
            out["extra_sessions"].append(o_sess.id)
            other = User(email=f"more{len(out['extra_sessions'])}@corp.local", password_hash=hash_password(PASSWORD),
                         role=UserRole.APPLICANT, name="추가")
            s.add(other)
            await s.flush()
        await s.commit()
    await engine.dispose()
    return out


def build_env(tmp_path: Path, *, brain: FakeBrain | None = None, stt: FakeSTT | None = None, tts: FakeTTS | None = None,
              tuning: dict | None = None, state: SessionState = SessionState.READY, slots: int = 2, max_followups: int = 2,
              coding: bool = False, extra_sessions: int = 0, max_sessions: int = 1) -> Env:
    brain = brain or FakeBrain(total_main=slots, max_followups=max_followups, coding=coding)
    stt, tts = stt or FakeSTT(), tts or FakeTTS()
    settings = make_settings(tmp_path / "test.db", media_root=tmp_path / "media", max_concurrent_sessions=max_sessions)
    engines = Engines(stt=stt, tts=tts, brain=brain, media=MediaStore(settings.media_root), tuning=fast_tuning(**(tuning or {})))
    app = create_app(settings, engines)
    ids = asyncio.run(_seed(settings.database_url, state=state, slots=slots, max_followups=max_followups, coding=coding,
                            extra_sessions=extra_sessions))
    client = TestClient(app)
    client.__enter__()
    env = Env(app, client, settings, engines, brain, stt, tts, settings.media_root, ids["session_id"], ids["application_id"],
              ids["user_id"], ids["job_id"], ids["company_id"],
              extra={k: ids[k] for k in ("other_user_id", "recruiter_id", "extra_sessions")})
    env.login()
    return env


# ── 메시지 헬퍼 ──────────────────────────────────────────────────────────────
def recv_until(ws, msg_type: str, *, limit: int = 60) -> tuple[list[dict], dict]:  # noqa: ANN001
    """msg_type 이 올 때까지 받은 메시지 목록과 그 메시지를 반환."""
    seen: list[dict] = []
    for _ in range(limit):
        m = ws.receive_json()
        if m["type"] == msg_type:
            return seen, m
        seen.append(m)
    raise AssertionError(f"{msg_type} 를 받지 못했습니다: {[m['type'] for m in seen]}")


def drain(ws) -> list[dict]:  # noqa: ANN001
    """ping→pong 왕복으로 그 시점까지 서버가 보낸 모든 메시지를 회수한다 (비차단 확인용)."""
    ws.send_json({"type": "ping"})
    seen, _ = recv_until(ws, "pong")
    return seen


def pcm(ms: int, amp: int = 3000) -> bytes:
    n = 16 * ms
    if amp == 0:
        return bytes(n * 2)
    t = np.arange(n) / 16000
    return (np.sin(2 * np.pi * 440 * t) * amp).astype(np.int16).tobytes()


class MediaSender:
    def __init__(self, ws) -> None:  # noqa: ANN001
        self.ws, self.seq = ws, 0

    def audio(self, ms: int = 500, amp: int = 3000) -> None:
        self.ws.send_bytes(protocol.build_frame(protocol.AUDIO, self.seq, pcm(ms, amp)))
        self.seq += 1

    def video(self, data: bytes = b"webm") -> None:
        self.ws.send_bytes(protocol.build_frame(protocol.VIDEO, self.seq, data))
        self.seq += 1


def start_answer(env: Env, ctl, turn_id: str) -> None:  # noqa: ANN001
    """tts_done → 카운트다운 수신 → answer_start → 서버가 답변 상태에 들어갈 때까지 대기. ctl 은 Ctl 래퍼."""
    ctl.send(type="tts_done", turn_id=turn_id)
    ctl.until("countdown")
    ctl.send(type="answer_start", turn_id=turn_id)
    wait_answering(env)


def wait_answering(env: Env) -> None:
    env.wait_for(lambda: (env.state_json().get("current_turn") or {}).get("remaining_sec") is not None, what="answering state")


def close_code(env_conn_ctx) -> int:  # noqa: ANN001
    """연결 직후 서버가 닫는 경우의 close code. 에러 메시지를 소비한 뒤 WebSocketDisconnect 를 기다린다."""
    with env_conn_ctx as ws:
        try:
            while True:
                ws.receive_json()
        except WebSocketDisconnect as e:
            return e.code


class Ctl:
    """제어 채널 래퍼: 받은 메시지를 모두 로그에 쌓아 순서/존재 여부를 나중에 검증할 수 있게 한다."""

    def __init__(self, ws) -> None:  # noqa: ANN001
        self.ws, self.log = ws, []

    def until(self, msg_type: str, **match: Any) -> dict:
        for _ in range(80):
            m = self.ws.receive_json()
            self.log.append(m)
            if m["type"] == msg_type and all(m.get(k) == v for k, v in match.items()):
                return m
        raise AssertionError(f"{msg_type} {match} 를 받지 못했습니다: {self.types()}")

    def send(self, **msg: Any) -> None:
        self.ws.send_json(msg)

    def types(self) -> list[str]:
        return [m["type"] for m in self.log]

    def of(self, msg_type: str) -> list[dict]:
        return [m for m in self.log if m["type"] == msg_type]

    def drain(self) -> list[dict]:
        self.ws.send_json({"type": "ping"})
        self.until("pong")
        return self.log
