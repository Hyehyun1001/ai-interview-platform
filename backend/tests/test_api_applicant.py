"""지원자 REST: 공고·지원·이력서·세션 수명주기 (TRD §7.2~§7.4)."""
from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.models import Application, InterviewSession, ResumeSnapshot
from app.models.enums import ApplicationStatus, JobStatus, SessionState, VectorStatus
from tests.fakes import main_json
from tests.pdf_factory import make_pdf
from tests.rest_env import wait_until

API = "/api/v1"
CONSENT = {"consent": True, "consent_version": "2026-01"}
RESUME = {"name": "김지원", "education": [{"school": "한빛대학교", "major": "컴퓨터공학"}], "skills": ["Java", "Redis"]}


async def _applied(rest, c, **jobkw):
    co, _hr = await rest.company_with_recruiter()
    await rest.applicant()
    await rest.login(c, "a@corp.local")
    job = await rest.job(co.id, **jobkw)
    r = await c.post(f"{API}/jobs/{job.id}/apply", json=CONSENT)
    assert r.status_code == 201, r.text
    return job, uuid.UUID(r.json()["application_id"])


# ── 오류 포맷 (Phase 4 #3) ───────────────────────────────────────────────────
async def test_validation_error_runtime_and_openapi_agree(rest):
    async with rest.client() as c:
        r = await c.post(f"{API}/auth/login", json={"email": "x"})
        assert r.status_code == 422
        body = r.json()
        assert set(body) == {"error"} and body["error"]["code"] == "VALIDATION_ERROR" and body["error"]["details"]["fields"]
        assert "input" not in r.text
        spec = (await c.get("/openapi.json")).json()
    assert "HTTPValidationError" not in spec["components"]["schemas"] and "ValidationError" not in spec["components"]["schemas"]
    ref = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]["422"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/ErrorEnvelope")
    assert {"code", "message", "details"} <= set(spec["components"]["schemas"]["ErrorBody"]["properties"])


# ── 공고 / 지원 ──────────────────────────────────────────────────────────────
async def test_jobs_list_detail_apply_flow(rest):
    async with rest.client() as c:
        co, _ = await rest.company_with_recruiter()
        await rest.applicant()
        await rest.login(c, "a@corp.local")
        open_job = await rest.job(co.id, "열린 공고")
        await rest.job(co.id, "임시저장", status=JobStatus.DRAFT)
        listing = (await c.get(f"{API}/jobs")).json()
        assert [j["title"] for j in listing["items"]] == ["열린 공고"] and listing["total"] == 1
        assert (await c.get(f"{API}/jobs", params={"q": "없는검색어"})).json()["items"] == []
        d = (await c.get(f"{API}/jobs/{open_job.id}")).json()
        assert d["duties"] and d["application_id"] is None
        assert "cutoff_score" not in json.dumps(d)  # 내부 설정 비노출
        assert (await c.get(f"{API}/jobs/{uuid.uuid4()}")).status_code == 404

        assert (await c.post(f"{API}/jobs/{open_job.id}/apply", json={"consent": False, "consent_version": "v1"})).json()["error"]["code"] == "CONSENT_REQUIRED"
        ok = await c.post(f"{API}/jobs/{open_job.id}/apply", json=CONSENT)
        assert ok.status_code == 201
        dup = await c.post(f"{API}/jobs/{open_job.id}/apply", json=CONSENT)
        assert dup.status_code == 409 and dup.json()["error"]["details"]["application_id"] == ok.json()["application_id"]
        mine = (await c.get(f"{API}/me/applications")).json()
        assert mine[0]["job"]["title"] == "열린 공고" and mine[0]["status"] == "applied" and mine[0]["result"] is None


async def test_apply_to_closed_or_expired_job_is_rejected_and_staff_cannot_apply(rest):
    from datetime import timedelta

    from app.models.base import utcnow

    async with rest.client() as c:
        co, _ = await rest.company_with_recruiter()
        await rest.applicant()
        await rest.login(c, "a@corp.local")
        expired = await rest.job(co.id, deadline_at=utcnow() - timedelta(hours=1))
        closed = await rest.job(co.id, "마감", status=JobStatus.CLOSED)
        for j in (expired, closed):
            assert (await c.post(f"{API}/jobs/{j.id}/apply", json=CONSENT)).json()["error"]["code"] == "JOB_CLOSED"
        assert (await c.get(f"{API}/jobs")).json()["items"] == []
    async with rest.client() as hr:
        await rest.login(hr, "hr@corp.local", "recruiter")
        assert (await hr.get(f"{API}/jobs")).status_code == 403


async def test_result_is_hidden_until_notified(rest):
    from app.models.base import utcnow
    from app.models.enums import FinalDecision

    async with rest.client() as c:
        job, app_id = await _applied(rest, c)
        async with rest.sm() as s:
            a = await s.get(Application, app_id)
            a.final_decision = FinalDecision.PASS
            await s.commit()
        assert (await c.get(f"{API}/me/applications")).json()[0]["result"] is None
        async with rest.sm() as s:
            a = await s.get(Application, app_id)
            a.result_notified_at = utcnow()
            await s.commit()
        assert (await c.get(f"{API}/me/applications")).json()[0]["result"] == "pass"


# ── 이력서 ───────────────────────────────────────────────────────────────────
async def test_manual_resume_and_confirm_rules(rest):
    async with rest.client() as c:
        job, app_id = await _applied(rest, c)
        assert (await c.get(f"{API}/me/resume")).status_code == 404
        # 작성 중 저장은 허용하되 기본 정보 미충족이면 지원 확정은 422
        r = await c.put(f"{API}/me/resume", json={"name": "김지원"})
        assert r.status_code == 200 and r.json()["basic_info_complete"] is False
        bad = await c.put(f"{API}/applications/{app_id}/resume", json={"source": "mypage"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "BASIC_INFO_REQUIRED"
        assert (await c.put(f"{API}/me/resume", json=RESUME)).json()["basic_info_complete"] is True
        ok = await c.put(f"{API}/applications/{app_id}/resume", json={"source": "mypage"})
        assert ok.status_code == 200 and ok.json()["data"]["name"] == "김지원"
        async with rest.sm() as s:
            assert (await s.get(Application, app_id)).status == ApplicationStatus.PREPARED
        # source=manual 은 data 필수
        assert (await c.put(f"{API}/applications/{app_id}/resume", json={"source": "manual"})).status_code == 422
        # 다른 지원자의 지원 건
        std = await c.get(f"{API}/applications/{app_id}/resume/standard")
        assert std.status_code == 200
    async with rest.client() as other:
        await rest.applicant("b@corp.local", "이다른")
        await rest.login(other, "b@corp.local")
        assert (await other.put(f"{API}/applications/{app_id}/resume", json={"source": "manual", "data": RESUME})).status_code == 404
        assert (await other.get(f"{API}/applications/{app_id}/resume/standard")).status_code == 404


async def test_pdf_upload_extracts_in_background_and_isolates_users(rest):
    pdf = make_pdf(["김지원\n학력\n한빛대학교 컴퓨터공학 2018.03 - 2022.02\n기술\nJava Redis\n" * 3])
    extracted = json.dumps({"name": "김지원", "education": [{"school": "한빛대학교", "major": "컴퓨터공학"}], "skills": ["Java", "Redis"]}, ensure_ascii=False)
    rest.llm.script.append(extracted)
    async with rest.client() as c:
        await rest.applicant()
        await rest.login(c, "a@corp.local")
        r = await c.post(f"{API}/me/resume/upload", files={"file": ("my resume.pdf", pdf, "application/pdf")})
        assert r.status_code == 202
        jid = r.json()["job_id"]

        async def done():
            return (await c.get(f"{API}/resume-jobs/{jid}")).json()["status"] != "running"

        await wait_until(done, 20)
        job = (await c.get(f"{API}/resume-jobs/{jid}")).json()
        assert job["status"] == "done" and job["fell_back"] is False and job["data"]["name"] == "김지원"
        # PRD §10 #11: 추출만으로는 마이페이지 등록본이 생기거나 바뀌지 않는다
        assert (await c.get(f"{API}/me/resume")).status_code == 404
        assert not list((rest.media_root / "resumes").glob("*.pdf"))  # 원본 PDF 는 남기지 않는다
        # 지원자가 "마이페이지에도 저장"을 고른 경우에만 PUT /me/resume 으로 갱신된다
        assert (await c.put(f"{API}/me/resume", json=job["data"])).status_code == 200
        me = (await c.get(f"{API}/me/resume")).json()
        assert me["source"] == "manual" and me["basic_info_complete"] is True
        # 잘못된 파일
        bad = await c.post(f"{API}/me/resume/upload", files={"file": ("a.txt", b"hello", "text/plain")})
        assert bad.status_code == 415 and bad.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    async with rest.client() as other:
        await rest.applicant("b@corp.local", "이다른")
        await rest.login(other, "b@corp.local")
        assert (await other.get(f"{API}/resume-jobs/{jid}")).status_code == 404


async def test_failed_extraction_keeps_existing_resume(rest):
    rest.llm.default = "{}"  # 아무것도 추출하지 못함 → fell_back
    pdf = make_pdf(["김지원\n학력\n한빛대학교 컴퓨터공학\n" * 5])
    async with rest.client() as c:
        await rest.applicant()
        await rest.login(c, "a@corp.local")
        await c.put(f"{API}/me/resume", json=RESUME)
        jid = (await c.post(f"{API}/me/resume/upload", files={"file": ("r.pdf", pdf, "application/pdf")})).json()["job_id"]

        async def done():
            return (await c.get(f"{API}/resume-jobs/{jid}")).json()["status"] != "running"

        await wait_until(done, 20)
        assert (await c.get(f"{API}/resume-jobs/{jid}")).json()["fell_back"] is True
        assert (await c.get(f"{API}/me/resume")).json()["source"] == "manual"  # 기존 등록본 보존


# ── 세션 수명주기 ────────────────────────────────────────────────────────────
async def test_session_requires_snapshot_and_is_idempotent(rest):
    async with rest.client() as c:
        job, app_id = await _applied(rest, c)
        r = await c.post(f"{API}/applications/{app_id}/session")
        assert r.status_code == 409 and r.json()["error"]["code"] == "BASIC_INFO_REQUIRED"
        await c.put(f"{API}/applications/{app_id}/resume", json={"source": "manual", "data": RESUME})
        first = await c.post(f"{API}/applications/{app_id}/session")
        assert first.status_code == 201 and first.json()["state"] == "created"
        again = await c.post(f"{API}/applications/{app_id}/session")
        assert again.status_code == 200 and again.json()["session_id"] == first.json()["session_id"]
        # 세션이 만들어진 뒤에는 이력서를 바꿀 수 없다
        assert (await c.put(f"{API}/applications/{app_id}/resume", json={"source": "manual", "data": RESUME})).json()["error"]["code"] == "SESSION_ALREADY_CREATED"


async def test_full_prepare_start_finish_flow(rest):
    rest.llm.default = main_json()
    async with rest.client() as c:
        job, app_id = await _applied(rest, c)
        await c.put(f"{API}/applications/{app_id}/resume", json={"source": "manual", "data": RESUME})
        sid = (await c.post(f"{API}/applications/{app_id}/session")).json()["session_id"]

        async def prepared():
            async with rest.sm() as s:
                return "prepared_at" in ((await s.get(InterviewSession, uuid.UUID(sid))).precomputed_context or {})

        await wait_until(prepared)
        async with rest.sm() as s:
            sess = await s.get(InterviewSession, uuid.UUID(sid))
            assert len(sess.precomputed_context["slots"]) == 10 and sess.precomputed_context["vector_status"] == "indexed"
            snap = (await s.execute(select(ResumeSnapshot).where(ResumeSnapshot.application_id == app_id))).scalar_one()
            assert snap.vector_status == VectorStatus.INDEXED
        assert rest.store.embedder.unloaded >= 1  # 인덱싱 뒤 임베딩 모델 해제 (TRD §2.3)

        # 장치 점검 없이는 시작할 수 없다
        assert (await c.post(f"{API}/sessions/{sid}/start")).json()["error"]["code"] == "DEVICE_CHECK_REQUIRED"
        assert (await c.post(f"{API}/sessions/{sid}/device-check", json={"camera": True, "mic": False, "speaker": True})).json()["all_ok"] is False
        assert (await c.post(f"{API}/sessions/{sid}/start")).json()["error"]["code"] == "DEVICE_CHECK_REQUIRED"
        assert (await c.post(f"{API}/sessions/{sid}/device-check", json={"camera": True, "mic": True, "speaker": True, "devices": {"mic": "내장"}})).json()["all_ok"]

        first = await c.post(f"{API}/sessions/{sid}/start")
        assert first.status_code in (200, 202)

        async def ready():
            r = await c.post(f"{API}/sessions/{sid}/start")
            return r.status_code == 200 and r.json()["status"] == "ready"

        await wait_until(ready)
        assert (await c.post(f"{API}/sessions/{sid}/ws-token")).status_code == 200  # READY 이므로 WS 토큰 발급 가능
        assert rest.llm.calls, "LLM warm-up 호출이 있어야 한다"

        # 면접을 시작하지 않은 세션은 종료할 수 없다
        assert (await c.post(f"{API}/sessions/{sid}/finish")).status_code == 409
        async with rest.sm() as s:
            sess = await s.get(InterviewSession, uuid.UUID(sid))
            sess.state = SessionState.IN_PROGRESS
            await s.commit()
        fin = await c.post(f"{API}/sessions/{sid}/finish")
        assert fin.status_code == 202 and fin.json()["report_status"] == "queued"
        assert (await c.post(f"{API}/sessions/{sid}/finish")).status_code == 202  # 멱등
        async with rest.sm() as s:
            from app.models import BackgroundJob, EvaluationReport

            assert (await s.get(Application, app_id)).status == ApplicationStatus.INTERVIEW_DONE
            assert len((await s.execute(select(EvaluationReport))).scalars().all()) == 1
            assert len((await s.execute(select(BackgroundJob).where(BackgroundJob.type == "report"))).scalars().all()) == 1


async def test_session_endpoints_are_owner_only(rest):
    async with rest.client() as c:
        job, app_id = await _applied(rest, c)
        await c.put(f"{API}/applications/{app_id}/resume", json={"source": "manual", "data": RESUME})
        sid = (await c.post(f"{API}/applications/{app_id}/session")).json()["session_id"]
    async with rest.client() as other:
        await rest.applicant("b@corp.local", "이다른")
        await rest.login(other, "b@corp.local")
        assert (await other.post(f"{API}/applications/{app_id}/session")).status_code == 404
        for path, body in ((f"/sessions/{sid}/device-check", {"camera": True, "mic": True, "speaker": True}), (f"/sessions/{sid}/start", None), (f"/sessions/{sid}/finish", None)):
            assert (await other.post(f"{API}{path}", json=body)).status_code == 404


async def test_start_reports_slot_unavailable_when_another_session_is_live(rest):
    rest.llm.default = main_json()
    async with rest.client() as c:
        job, app_id = await _applied(rest, c)
        await c.put(f"{API}/applications/{app_id}/resume", json={"source": "manual", "data": RESUME})
        sid = (await c.post(f"{API}/applications/{app_id}/session")).json()["session_id"]
        await c.post(f"{API}/sessions/{sid}/device-check", json={"camera": True, "mic": True, "speaker": True})
        rest.app.state.session_manager._runtimes[uuid.uuid4()] = object()  # noqa: SLF001  다른 지원자의 진행 중 세션
        r = await c.post(f"{API}/sessions/{sid}/start")
        assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_SLOT_UNAVAILABLE" and r.json()["error"]["details"]["retry_after_sec"] == 30
        rest.app.state.session_manager._runtimes.clear()  # noqa: SLF001
