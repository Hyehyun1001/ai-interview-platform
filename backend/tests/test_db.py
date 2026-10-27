"""DB 연결·스키마·제약·암호화 검증."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import (Application, Base, Company, EvalWeight, FollowupRule, InterviewSession, InterviewTurn, JobPosting,
                        User)
from app.models.enums import ApplicationStatus, FinalDecision, SessionState, TurnKind, UserRole


async def _user(session, email="u@corp.local", role=UserRole.APPLICANT, **kw) -> User:
    u = User(email=email, password_hash="x", role=role, name=kw.pop("name", "김지원"), **kw)
    session.add(u)
    await session.flush()
    return u


async def _job(session) -> JobPosting:
    c = Company(name="다온커머스")
    session.add(c)
    await session.flush()
    j = JobPosting(company_id=c.id, title="백엔드 개발자")
    session.add(j)
    await session.flush()
    return j


async def test_db_connection_and_pragmas(session):
    assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    if session.bind.dialect.name != "sqlite":
        pytest.skip("PRAGMA 는 SQLite 전용 — PostgreSQL 은 FK 를 항상 강제한다 (test_foreign_keys 계열이 검증)")
    assert (await session.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    assert (await session.execute(text("PRAGMA journal_mode"))).scalar_one().lower() == "wal"


async def test_all_models_have_tables(app):
    async with app.state.engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    expected = set(Base.metadata.tables)
    assert expected <= tables
    assert {"users", "job_postings", "applications", "interview_sessions", "interview_turns", "jobs"} <= tables
    assert len(expected) == 25


async def test_foreign_key_enforced(session):
    session.add(Application(user_id=uuid.uuid4(), job_id=uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_application_defaults_and_unique_user_job(session):
    u, j = await _user(session), await _job(session)
    a = Application(user_id=u.id, job_id=j.id)
    session.add(a)
    await session.flush()
    assert a.status is ApplicationStatus.APPLIED and a.final_decision is FinalDecision.PENDING
    session.add(Application(user_id=u.id, job_id=j.id))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_status_enum_has_no_decision_values(session):
    """합불 단일 출처: applications.status 에 passed/failed 가 없어야 한다."""
    assert {m.value for m in ApplicationStatus} == {"applied", "prepared", "interviewing", "interview_done", "report_ready"}
    u, j = await _user(session), await _job(session)
    session.add(Application(user_id=u.id, job_id=j.id))
    await session.flush()
    with pytest.raises((IntegrityError, StatementError, LookupError)):
        await session.execute(text("UPDATE applications SET status='passed'"))


async def test_email_unique(session):
    await _user(session, email="dup@corp.local")
    session.add(User(email="dup@corp.local", password_hash="x", role=UserRole.APPLICANT, name="다른사람"))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_pii_is_encrypted_at_rest_and_decrypted_on_read(session):
    u = await _user(session, name="홍길동", phone="010-1234-5678", birth_date="1995-03-21", gender="male")
    uid = u.id  # expire_all 이후 만료된 객체 속성 접근은 비동기 세션에서 암묵적 IO 를 일으키므로 미리 보관
    await session.commit()
    raw = (await session.execute(text("SELECT name, phone, birth_date, gender FROM users WHERE id = :i"),
                                 {"i": uid.hex})).one()
    for plain in ("홍길동", "010-1234-5678", "1995-03-21", "male"):
        assert all(plain not in col for col in raw), f"{plain} 이 평문으로 저장됨"
    assert raw[0].startswith("gAAAA")  # Fernet 토큰
    session.expire_all()
    again = await session.get(User, uid)
    assert (again.name, again.phone, again.birth_date, again.gender) == ("홍길동", "010-1234-5678", "1995-03-21", "male")


async def test_utc_datetime_roundtrip_and_naive_rejected(session):
    u = await _user(session)
    ts = datetime(2026, 10, 26, 9, 30, tzinfo=timezone(timedelta(hours=9)))  # KST
    u.resume_popup_dismissed_at = ts
    uid = u.id
    await session.commit()
    session.expire_all()
    got = (await session.get(User, uid)).resume_popup_dismissed_at
    assert got.tzinfo is not None and got == ts and got.utcoffset() == timedelta(0)
    u2 = await _user(session, email="n@corp.local")
    u2.resume_popup_dismissed_at = datetime(2026, 1, 1)  # naive
    with pytest.raises((ValueError, StatementError)):
        await session.flush()


async def test_eval_weights_must_sum_to_100(session):
    j = await _job(session)
    session.add(EvalWeight(job_id=j.id))  # 기본값 25+20+15+10+30+0 = 100
    await session.flush()
    j2 = await _job(session)
    session.add(EvalWeight(job_id=j2.id, logic=50))  # 합계 130
    with pytest.raises(IntegrityError):
        await session.flush()


@pytest.mark.parametrize("n", [0, 5])
async def test_followup_rule_range(session, n):
    j = await _job(session)
    session.add(FollowupRule(job_id=j.id, max_followups=n))
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_turn_unique_and_cascade_delete(session):
    u, j = await _user(session), await _job(session)
    a = Application(user_id=u.id, job_id=j.id)
    session.add(a)
    await session.flush()
    s = InterviewSession(application_id=a.id, state=SessionState.CREATED)
    session.add(s)
    await session.flush()
    session.add(InterviewTurn(session_id=s.id, turn_no=1, kind=TurnKind.MAIN, question_text="자기소개", answer_text="저는 홍길동입니다"))
    await session.flush()
    session.add(InterviewTurn(session_id=s.id, turn_no=1, kind=TurnKind.FOLLOWUP, question_text="중복 번호"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()

    # 사용자 삭제 → 지원 → 세션 → 턴까지 연쇄 삭제 (계정 삭제 요청 NFR-S7)
    await session.execute(text("DELETE FROM users WHERE id = :i"), {"i": u.id.hex})
    for table in ("applications", "interview_sessions", "interview_turns"):
        assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
