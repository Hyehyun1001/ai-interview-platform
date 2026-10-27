"""관리자·미디어 REST (TRD §7.6, §7.8): 회사 스코프, 대시보드 집계, 타임라인, Range 오디오."""
from __future__ import annotations

import struct
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.api.media import parse_range, wav_header
from app.models import Application, AuditLog, Notification, User
from app.models.base import utcnow
from app.models.enums import ApplicationStatus, FinalDecision, ReportStatus

API = "/api/v1"


async def _staff(rest, c, co_name="다온커머스", email="hr@corp.local"):
    co, hr = await rest.company_with_recruiter(co_name, email)
    await rest.login(c, email, "recruiter")
    return co, hr


async def test_admin_endpoints_require_staff_role_and_company(rest):
    async with rest.client() as anon:
        assert (await anon.get(f"{API}/admin/dashboard")).status_code == 401
    async with rest.client() as c:
        await rest.applicant()
        await rest.login(c, "a@corp.local")
        for path in ("/admin/dashboard", "/admin/applications", "/admin/system/metrics", "/admin/notifications", "/admin/schedules"):
            assert (await c.get(f"{API}{path}")).status_code == 403, path
    async with rest.client() as c:  # 회사 없는 담당자
        from app.core.security import hash_password
        from app.models.enums import UserRole

        await rest.add(User(email="nobody@corp.local", password_hash=hash_password("Passw0rd!"), role=UserRole.RECRUITER, name="무소속"))
        await rest.login(c, "nobody@corp.local", "recruiter")
        assert (await c.get(f"{API}/admin/dashboard")).status_code == 403


async def test_dashboard_aggregates_only_own_company(rest):
    async with rest.client() as c:
        co, _ = await _staff(rest, c)
        other_co, _ = await rest.company_with_recruiter("타사", "other-hr@corp.local")
        ua, ub, uc = await rest.applicant("a@corp.local", "김지원"), await rest.applicant("b@corp.local", "이다른"), await rest.applicant("c@corp.local", "박세번째")
        job = await rest.job(co.id, "백엔드", job_category="개발", coding_test_enabled=True, coding_test_time_limit_sec=1800,
                             deadline_at=utcnow() + timedelta(hours=10))
        job2 = await rest.job(co.id, "디자이너", job_category="디자인")
        foreign = await rest.job(other_co.id, "타사 공고")
        a1, _, _ = await rest.finished_interview(ua, job, score=80)
        a2, _, _ = await rest.finished_interview(ub, job, score=60)
        await rest.finished_interview(uc, foreign, score=99)  # 타사 — 보이면 안 된다
        async with rest.sm() as s:
            x = await s.get(Application, a1.id)
            x.status, x.final_decision = ApplicationStatus.REPORT_READY, FinalDecision.PASS
            y = await s.get(Application, a2.id)
            y.status = ApplicationStatus.REPORT_READY
            await s.commit()
        d = (await c.get(f"{API}/admin/dashboard", params={"range": "30d"})).json()
    assert d["summary"]["open_jobs"] == {"total": 2, "coding_on": 1}
    assert d["summary"]["unreviewed_applicants"] == 1  # a2 (pending, report_ready, 미열람); a1 은 결정됨
    assert d["summary"]["closing_soon_jobs"] == 1
    cats = {x["category"]: x for x in d["stats"]["by_job_category"]}
    assert set(cats) == {"개발"} and cats["개발"]["avg_score"] == 70.0 and cats["개발"]["applicants"] == 2
    assert cats["개발"]["pass_rate"] == 1.0  # 결정된 1건(pass) 중 pass 1건
    assert len(d["stats"]["monthly_applicants"]) == 6 and d["stats"]["monthly_applicants"][-1]["count"] == 2
    titles = {j["title"]: j for j in d["recent_jobs"]}
    assert set(titles) == {"백엔드", "디자이너"} and titles["백엔드"]["applicant_count"] == 2 and titles["백엔드"]["unreviewed_count"] == 1
    names = {a["name"] for a in d["recent_completed_applicants"]}
    assert names == {"김지원", "이다른"}
    assert all(a["report_status"] == "queued" for a in d["recent_completed_applicants"])  # 리포트 행이 없으면 queued
    assert "birth" not in str(d) and "phone" not in str(d)


async def test_pass_rate_is_null_when_nothing_decided(rest):
    async with rest.client() as c:
        co, _ = await _staff(rest, c)
        u = await rest.applicant()
        job = await rest.job(co.id)
        await rest.finished_interview(u, job, score=75)
        d = (await c.get(f"{API}/admin/dashboard")).json()
    assert d["stats"]["by_job_category"][0]["pass_rate"] is None


async def test_applications_list_filters_and_scoping(rest):
    async with rest.client() as c:
        co, _ = await _staff(rest, c)
        other_co, _ = await rest.company_with_recruiter("타사", "o@corp.local")
        u1, u2 = await rest.applicant("a@corp.local", "가"), await rest.applicant("b@corp.local", "나")
        j1, j2, jf = await rest.job(co.id, "J1"), await rest.job(co.id, "J2"), await rest.job(other_co.id, "타사")
        a1, _, _ = await rest.finished_interview(u1, j1, score=50)
        await rest.finished_interview(u2, j2, score=90)
        await rest.finished_interview(u1, jf, score=99)
        allr = (await c.get(f"{API}/admin/applications")).json()
        assert allr["total"] == 2 and {i["job_title"] for i in allr["items"]} == {"J1", "J2"}
        assert (await c.get(f"{API}/admin/applications", params={"sort": "score_desc"})).json()["items"][0]["name"] == "나"
        assert (await c.get(f"{API}/admin/applications", params={"job_id": str(j1.id)})).json()["total"] == 1
        assert (await c.get(f"{API}/admin/applications", params={"stage": "report_ready"})).json()["total"] == 0
        assert (await c.get(f"{API}/admin/applications", params={"limit": 1})).json()["items"].__len__() == 1
        assert (await c.get(f"{API}/admin/applications", params={"stage": "bogus"})).status_code == 422


async def test_detail_timeline_and_cross_company_404(rest):
    async with rest.client() as c:
        co, hr = await _staff(rest, c)
        u = await rest.applicant()
        job = await rest.job(co.id)
        app, sess, turn = await rest.finished_interview(u, job, score=82.5)
        d = (await c.get(f"{API}/admin/applications/{app.id}")).json()
        assert d["report"] is None  # 리포트가 done 이 아니면 평가 요약을 내리지 않는다
        assert d["applicant_name"] == "김지원" and d["ai_total_score"] == 82.5 and d["report_status"] == "queued"
        t = (await c.get(f"{API}/admin/applications/{app.id}/timeline")).json()
        turn_out = t["turns"][0]
        assert turn_out["audio_url"] == f"/api/v1/media/turns/{turn.id}/audio" and turn_out["duration_ms"] == 3000
        assert turn_out["segments"] == [{"start_ms": 0, "end_ms": 3000, "kind": "speech", "text": "저는 백엔드 개발자입니다.", "ai_comment": None, "severity": None, "words": None}]
        assert turn_out["gaze_events"] == [{"start_ms": 500, "end_ms": 2200, "kind": "gaze_away"}]
        assert turn_out["review"] is None
        # 열람 확인은 최초 1회만 기록되고 반복해도 204 (멱등)
        assert (await c.post(f"{API}/admin/applications/{app.id}/reviewed")).status_code == 204
        async with rest.sm() as s:
            first = (await s.get(Application, app.id)).first_reviewed_at
        assert first is not None and (await c.post(f"{API}/admin/applications/{app.id}/reviewed")).status_code == 204
        async with rest.sm() as s:
            assert (await s.get(Application, app.id)).first_reviewed_at == first
            actions = [a.action for a in (await s.execute(select(AuditLog).where(AuditLog.user_id == hr.id))).scalars()]
        assert "view_application" in actions and "view_timeline" in actions
    async with rest.client() as other:
        await rest.company_with_recruiter("타사", "o@corp.local")
        await rest.login(other, "o@corp.local", "recruiter")
        for path in (f"/admin/applications/{app.id}", f"/admin/applications/{app.id}/timeline"):
            assert (await other.get(f"{API}{path}")).status_code == 404
        assert (await other.post(f"{API}/admin/applications/{app.id}/reviewed")).status_code == 404
        assert (await other.get(f"{API}/admin/applications/{uuid.uuid4()}")).status_code == 404


async def test_timeline_without_audio_has_null_url(rest):
    async with rest.client() as c:
        co, _ = await _staff(rest, c)
        job = await rest.job(co.id)
        app, _, _ = await rest.finished_interview(await rest.applicant(), job, with_audio=False)
        t = (await c.get(f"{API}/admin/applications/{app.id}/timeline")).json()
    assert t["turns"][0]["audio_url"] is None


async def test_schedules_notifications_and_metrics(rest):
    async with rest.client() as c:
        co, hr = await _staff(rest, c)
        job = await rest.job(co.id)
        starts = utcnow() + timedelta(hours=2)
        ok = await c.post(f"{API}/admin/schedules", json={"title": "1차 면접", "type": "interview1", "job_id": str(job.id), "starts_at": starts.isoformat()})
        assert ok.status_code == 201
        # 검증: 시간대 없음 / 종료 < 시작 / 남의 공고
        assert (await c.post(f"{API}/admin/schedules", json={"title": "x", "type": "interview1", "starts_at": "2026-01-01T10:00:00"})).status_code == 422
        assert (await c.post(f"{API}/admin/schedules", json={"title": "x", "type": "deadline", "starts_at": starts.isoformat(), "ends_at": (starts - timedelta(hours=1)).isoformat()})).status_code == 422
        assert (await c.post(f"{API}/admin/schedules", json={"title": "x", "type": "deadline", "starts_at": starts.isoformat(), "job_id": str(uuid.uuid4())})).status_code == 404
        listed = (await c.get(f"{API}/admin/schedules")).json()
        assert [s["title"] for s in listed] == ["1차 면접"]
        assert (await c.get(f"{API}/admin/dashboard")).json()["summary"]["upcoming_interviews"]["total"] == 1

        n = Notification(user_id=hr.id, type="new_application", payload={"x": 1})
        await rest.add(n, Notification(user_id=hr.id, type="report_ready", payload=None, read_at=utcnow()))
        feed = (await c.get(f"{API}/admin/notifications")).json()
        assert feed["unread_count"] == 1 and len(feed["items"]) == 2
        assert (await c.post(f"{API}/admin/notifications/{n.id}/read")).status_code == 204
        assert (await c.get(f"{API}/admin/notifications")).json()["unread_count"] == 0
        assert (await c.post(f"{API}/admin/notifications/{uuid.uuid4()}/read")).status_code == 404

        m = (await c.get(f"{API}/admin/system/metrics")).json()
        assert m["pressure"] in ("normal", "warn", "critical") and m["free_gb"] > 0
        assert m["external_transfer"] == {"enabled": False, "tts_edge": False, "cloud_fallback": False, "count": 0}
        assert set(m["models"]) == {"llm", "stt", "tts", "embed"}
    async with rest.client() as other:  # 다른 회사 담당자는 이 일정·알림을 볼 수 없다
        await rest.company_with_recruiter("타사", "o@corp.local")
        await rest.login(other, "o@corp.local", "recruiter")
        assert (await other.get(f"{API}/admin/schedules")).json() == []


def test_pressure_thresholds_follow_trd():
    from app.api.admin import pressure_for

    assert [pressure_for(x) for x in (3.0, 2.5, 2.49, 1.2, 1.19, 0.1)] == ["normal", "normal", "warn", "warn", "critical", "critical"]


# ── 오디오 스트리밍 ──────────────────────────────────────────────────────────
def test_parse_range_variants():
    assert parse_range(None, 100) is None and parse_range("garbage", 100) is None
    assert parse_range("bytes=0-9", 100) == (0, 9)
    assert parse_range("bytes=90-", 100) == (90, 99)
    assert parse_range("bytes=-10", 100) == (90, 99)
    assert parse_range("bytes=50-500", 100) == (50, 99)  # 끝이 범위를 넘으면 잘라 준다
    for bad in ("bytes=100-", "bytes=60-50", "bytes=-0"):
        try:
            parse_range(bad, 100)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_wav_header_is_valid_riff():
    h = wav_header(6400)
    assert len(h) == 44 and h[:4] == b"RIFF" and h[8:12] == b"WAVE"
    assert struct.unpack("<I", h[4:8])[0] == 36 + 6400 and struct.unpack("<I", h[40:44])[0] == 6400
    ch, rate = struct.unpack("<HI", h[22:24] + h[24:28])
    assert (ch, rate) == (1, 16000)


async def test_audio_streams_with_ranges_and_enforces_access(rest):
    pcm = bytes(range(256)) * 25
    async with rest.client() as c:
        co, hr = await _staff(rest, c)
        job = await rest.job(co.id)
        user = await rest.applicant()
        _, _, turn = await rest.finished_interview(user, job)
        url = f"{API}/media/turns/{turn.id}/audio"
        full = await c.get(url)
        assert full.status_code == 200 and full.headers["accept-ranges"] == "bytes" and full.headers["content-type"] == "audio/wav"
        body = full.content
        assert len(body) == 44 + len(pcm) and body[44:] == pcm and body[:4] == b"RIFF"
        assert int(full.headers["content-length"]) == len(body)
        # 헤더 경계를 가로지르는 범위, PCM 안쪽 범위, 접미 범위
        r1 = await c.get(url, headers={"Range": "bytes=40-49"})
        assert r1.status_code == 206 and r1.content == body[40:50] and r1.headers["content-range"] == f"bytes 40-49/{len(body)}"
        r2 = await c.get(url, headers={"Range": "bytes=1000-1999"})
        assert r2.content == body[1000:2000]
        r3 = await c.get(url, headers={"Range": "bytes=-16"})
        assert r3.status_code == 206 and r3.content == body[-16:]
        r4 = await c.get(url, headers={"Range": f"bytes={len(body)}-"})
        assert r4.status_code == 416 and r4.headers["content-range"] == f"bytes */{len(body)}"
        async with rest.sm() as s:  # 재생 시작(start=0)만 감사 로그에 남는다: full + 위 Range 중 start 0 은 없음
            plays = (await s.execute(select(AuditLog).where(AuditLog.action == "play_audio", AuditLog.user_id == hr.id))).scalars().all()
        assert len(plays) == 1
    async with rest.client() as owner:  # 본인 지원자
        await rest.login(owner, "a@corp.local")
        assert (await owner.get(url)).status_code == 200
    async with rest.client() as stranger:
        await rest.applicant("b@corp.local", "남")
        await rest.login(stranger, "b@corp.local")
        assert (await stranger.get(url)).status_code == 404
    async with rest.client() as foreign_hr:
        await rest.company_with_recruiter("타사", "o@corp.local")
        await rest.login(foreign_hr, "o@corp.local", "recruiter")
        assert (await foreign_hr.get(url)).status_code == 404
    async with rest.client() as anon:
        assert (await anon.get(url)).status_code == 401
        assert (await anon.get(f"{API}/media/turns/{uuid.uuid4()}/audio")).status_code == 401


async def test_audio_missing_file_is_404(rest):
    async with rest.client() as c:
        co, _ = await _staff(rest, c)
        job = await rest.job(co.id)
        _, _, turn = await rest.finished_interview(await rest.applicant(), job, with_audio=False)
        assert (await c.get(f"{API}/media/turns/{turn.id}/audio")).status_code == 404


_ = ReportStatus


async def test_schedule_update_delete_job_history_and_new_application_notification(rest):
    from datetime import timedelta

    from app.models.base import utcnow

    co, _hr = await rest.company_with_recruiter()
    job = await rest.job(co.id)
    await rest.company_with_recruiter("타사", "o@corp.local")
    start = utcnow() + timedelta(days=1)
    body = {"title": "1차 면접", "type": "interview1", "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=1)).isoformat()}
    async with rest.client() as c:
        await rest.login(c, "hr@corp.local", "recruiter")
        sid = (await c.post(f"{API}/admin/schedules", json=body)).json()["id"]
        up = await c.put(f"{API}/admin/schedules/{sid}", json={**body, "title": "수정된 면접", "job_id": str(job.id)})
        assert up.status_code == 200 and up.json()["title"] == "수정된 면접" and up.json()["job_id"] == str(job.id)
        bad = await c.put(f"{API}/admin/schedules/{sid}", json={**body, "ends_at": (start - timedelta(hours=1)).isoformat()})
        assert bad.status_code == 422  # 종료 < 시작
        assert (await c.put(f"{API}/admin/schedules/{sid}", json={**body, "job_id": str(uuid.uuid4())})).status_code == 404
    async with rest.client() as o:  # 타사 담당자는 수정·삭제할 수 없고 존재도 알 수 없다
        await rest.login(o, "o@corp.local", "recruiter")
        assert (await o.put(f"{API}/admin/schedules/{sid}", json=body)).status_code == 404
        assert (await o.delete(f"{API}/admin/schedules/{sid}")).status_code == 404
    async with rest.client() as c:
        await rest.login(c, "hr@corp.local", "recruiter")
        assert (await c.delete(f"{API}/admin/schedules/{sid}")).status_code == 204
        assert (await c.get(f"{API}/admin/schedules")).json() == []

        # 지원자가 지원하면 담당자에게 new_application 알림(식별자만)이 쌓인다
        await rest.applicant()
    async with rest.client() as a:
        await rest.login(a, "a@corp.local")
        assert (await a.post(f"{API}/jobs/{job.id}/apply", json={"consent": True, "consent_version": "2026-01"})).status_code == 201
    async with rest.client() as c:
        await rest.login(c, "hr@corp.local", "recruiter")
        n = (await c.get(f"{API}/admin/notifications")).json()["items"]
        assert [x["type"] for x in n] == ["new_application"] and set(n[0]["payload"]) == {"application_id", "job_id"}
        mine = (await c.post(f"{API}/admin/jobs", json={"title": "이력 공고"})).json()
        h = (await c.get(f"{API}/admin/job-history")).json()
        assert h["total"] == 1 and h["items"][0]["action"] == "created" and h["items"][0]["job_title"] == "이력 공고" and h["items"][0]["actor_name"] == "담당자"
        assert mine["id"] == h["items"][0]["job_id"]
    async with rest.client() as o:
        await rest.login(o, "o@corp.local", "recruiter")
        assert (await o.get(f"{API}/admin/job-history")).json()["total"] == 0
