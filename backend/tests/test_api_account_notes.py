"""PATCH/DELETE /me (APP-04, NFR-S7) 와 내부 메모 API (TRD §7.6)."""
from __future__ import annotations

from sqlalchemy import func, select

from app.models import Application, InterviewSession, Resume, User
from tests.conftest import API
from tests.rest_env import PW, rest  # noqa: F401


async def test_me_exposes_profile_and_patch_updates_name_phone_only(rest):
    async with rest.client() as c:
        await rest.applicant()
        await rest.login(c, "a@corp.local")
        r = await c.patch(f"{API}/me", json={"name": "김새이름", "phone": "010-1234-5678"})
        assert r.status_code == 200 and r.json()["name"] == "김새이름" and r.json()["phone"] == "010-1234-5678"
        assert (await c.get(f"{API}/me")).json()["name"] == "김새이름"
        # 생년월일·성별은 수정할 수 없다 (extra=forbid → 422)
        assert (await c.patch(f"{API}/me", json={"birth_date": "1999-01-01"})).status_code == 422
        assert (await c.patch(f"{API}/me", json={"phone": "123"})).status_code == 422


async def test_password_change_requires_current_password(rest):
    async with rest.client() as c:
        await rest.applicant()
        await rest.login(c, "a@corp.local")
        bad = await c.patch(f"{API}/me", json={"current_password": "Wrong123!", "new_password": "NewPassw0rd!"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "WRONG_PASSWORD"
        assert (await c.patch(f"{API}/me", json={"new_password": "NewPassw0rd!"})).status_code == 422  # 현재 비밀번호 누락
        assert (await c.patch(f"{API}/me", json={"current_password": PW, "new_password": "NewPassw0rd!"})).status_code == 200
    async with rest.client() as c2:
        old = await c2.post(f"{API}/auth/login", json={"email": "a@corp.local", "password": PW, "role": "applicant"})
        assert old.status_code == 401
        assert (await c2.post(f"{API}/auth/login", json={"email": "a@corp.local", "password": "NewPassw0rd!", "role": "applicant"})).status_code == 200


async def test_delete_me_removes_rows_files_and_vectors(rest):
    co, _hr = await rest.company_with_recruiter()
    job = await rest.job(co.id)
    user = await rest.applicant()
    _app, sess, turn = await rest.finished_interview(user, job)
    await rest.add(Resume(user_id=user.id, source="manual", data={"name": "김지원"}, basic_info_complete=True))
    media_dir = rest.media_root / str(sess.id)
    assert media_dir.exists()
    from app.schemas.resume import ResumeSchema  # noqa: PLC0415

    rest.store.index_resume("snap-1", str(_app.id), str(user.id), ResumeSchema.model_validate({"name": "김지원", "skills": ["Java", "Redis"]}))
    col = rest.store._collection("resume_chunks_bgem3_v1")  # noqa: SLF001
    assert col.get(where={"user_id": str(user.id)})["ids"]
    async with rest.client() as c:
        await rest.login(c, "a@corp.local")
        assert (await c.request("DELETE", f"{API}/me", json={"password": "Wrong123!"})).status_code == 422
        assert media_dir.exists()  # 틀린 비밀번호면 아무것도 지우지 않는다
        assert (await c.request("DELETE", f"{API}/me", json={"password": PW})).status_code == 204
        assert (await c.get(f"{API}/me")).status_code == 401  # 쿠키 삭제 + 계정 없음
    async with rest.sm() as s:
        for model in (User, Application, InterviewSession, Resume):
            assert (await s.execute(select(func.count()).select_from(model))).scalar_one() == (1 if model is User else 0), model  # User: 담당자만 남는다
    assert not media_dir.exists()
    assert not col.get(where={"user_id": str(user.id)})["ids"]  # 벡터 인덱스도 지워졌다


async def test_delete_me_blocked_while_interviewing_and_for_recruiters(rest):
    from app.models.enums import SessionState

    co, _hr = await rest.company_with_recruiter()
    job = await rest.job(co.id)
    user = await rest.applicant()
    _app, sess, _t = await rest.finished_interview(user, job)
    async with rest.sm() as s:
        row = await s.get(InterviewSession, sess.id)
        row.state = SessionState.IN_PROGRESS
        await s.commit()
    async with rest.client() as c:
        await rest.login(c, "a@corp.local")
        r = await c.request("DELETE", f"{API}/me", json={"password": PW})
        assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_IN_PROGRESS"
    async with rest.client() as h:
        await rest.login(h, "hr@corp.local", "recruiter")
        assert (await h.request("DELETE", f"{API}/me", json={"password": PW})).status_code == 403


async def test_notes_are_company_scoped_and_ordered(rest):
    co, _hr = await rest.company_with_recruiter()
    job = await rest.job(co.id)
    user = await rest.applicant()
    app, _s, _t = await rest.finished_interview(user, job)
    await rest.company_with_recruiter("타사", "other@corp.local")
    async with rest.client() as h:
        await rest.login(h, "hr@corp.local", "recruiter")
        assert (await h.get(f"{API}/admin/applications/{app.id}/notes")).json() == []
        assert (await h.post(f"{API}/admin/applications/{app.id}/notes", json={"body": "  "})).status_code == 422
        assert (await h.post(f"{API}/admin/applications/{app.id}/notes", json={"body": "x" * 2001})).status_code == 422
        n1 = await h.post(f"{API}/admin/applications/{app.id}/notes", json={"body": "첫 메모"})
        assert n1.status_code == 201 and n1.json()["mine"] is True and n1.json()["author_name"] == "담당자"
        await h.post(f"{API}/admin/applications/{app.id}/notes", json={"body": "둘째 메모"})
        bodies = [n["body"] for n in (await h.get(f"{API}/admin/applications/{app.id}/notes")).json()]
        assert bodies == ["둘째 메모", "첫 메모"]
    async with rest.client() as o:
        await rest.login(o, "other@corp.local", "recruiter")
        assert (await o.get(f"{API}/admin/applications/{app.id}/notes")).status_code == 404
        assert (await o.post(f"{API}/admin/applications/{app.id}/notes", json={"body": "침입"})).status_code == 404
    async with rest.client() as a:  # 지원자는 접근 불가
        await rest.login(a, "a@corp.local")
        assert (await a.get(f"{API}/admin/applications/{app.id}/notes")).status_code == 403
