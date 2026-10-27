"""공고 작성 마법사 · 지원자 비교 · 결정 · 안내 메일 REST."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from sqlalchemy import select

from app.models import Application, AuditLog, EvaluationReport, JobPosting, JobQuestion, RecruiterNote
from app.models.base import utcnow
from app.models.enums import ApplicationStatus, FinalDecision, JobStatus, QuestionBankStatus, ReportStatus
from tests.rest_env import wait_until
from tests.test_worker_report import make_session

API = "/api/v1"
FULL = {"title": "백엔드 개발자", "job_category": "개발", "headcount": 2, "duties": "주문 API 개발과 성능 개선", "requirements": "Java, Redis 경험",
        "deadline_at": (utcnow() + timedelta(days=10)).isoformat()}


async def staff(rest, c, name="다온커머스", email="hr@corp.local"):
    co, hr = await rest.company_with_recruiter(name, email)
    await rest.login(c, email, "recruiter")
    return co, hr


async def test_wizard_draft_update_and_stale_detection(rest):
    async with rest.client() as c:
        await staff(rest, c)
        assert (await c.post(f"{API}/admin/jobs", json={})).status_code == 422  # 제목 없이는 임시 저장도 불가
        r = await c.post(f"{API}/admin/jobs", json={"title": "임시 공고"})
        assert r.status_code == 201
        job = r.json()
        assert job["status"] == "draft" and job["weights"]["weights"]["logic"] == 20 and job["followup_rules"]["max_followups"] == 2 and job["questions"] == []
        upd = await c.put(f"{API}/admin/jobs/{job['id']}", json={**FULL, "updated_at": job["updated_at"]})
        assert upd.status_code == 200 and upd.json()["headcount"] == 2
        stale = await c.put(f"{API}/admin/jobs/{job['id']}", json={"title": "x", "updated_at": job["updated_at"]})  # 이미 바뀐 updated_at
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_UPDATE"
        assert (await c.put(f"{API}/admin/jobs/{job['id']}", json={"title": ""})).status_code == 422
        assert (await c.put(f"{API}/admin/jobs/{job['id']}", json={"unknown": 1})).status_code == 422  # extra 금지
        assert (await c.get(f"{API}/admin/jobs")).json()["total"] == 1


async def test_questions_set_limits_and_fairness(rest):
    async with rest.client() as c:
        await staff(rest, c)
        j = (await c.post(f"{API}/admin/jobs", json=FULL)).json()
        url = f"{API}/admin/jobs/{j['id']}/questions"
        ok = await c.put(url, json={"items": [{"text": "자기소개를 해 주세요", "category": "인성", "time_limit_sec": 90}, {"text": "Redis 를 쓴 이유는?"}]})
        assert [q["order_no"] for q in ok.json()] == [1, 2]
        again = await c.put(url, json={"items": [{"text": "새 질문입니다 설명해 주세요"}]})  # 통째로 교체 (UNIQUE order_no 충돌 없음)
        assert [q["text"] for q in again.json()] == ["새 질문입니다 설명해 주세요"]
        assert (await c.put(url, json={"items": [{"text": f"질문 {i} 입니다"} for i in range(11)]})).status_code == 422
        bad = await c.put(url, json={"items": [{"text": "좋은 질문입니다"}, {"text": "결혼 계획이 있으신가요?"}]})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "FORBIDDEN_QUESTION" and bad.json()["error"]["details"]["index"] == 1
        assert (await c.get(f"{API}/admin/jobs/{j['id']}")).json()["questions"][0]["text"] == "새 질문입니다 설명해 주세요"  # 거부 시 기존 유지


async def test_weights_validation_cutoff_and_recalculation(rest):
    co, hr, user, job, app, sess, turns = await make_session(rest, cutoff=70)
    async with rest.sm() as s:
        a = await s.get(Application, app.id)
        a.status, a.ai_total_score = ApplicationStatus.REPORT_READY, 72
        await s.commit()
    async with rest.client() as c:
        await rest.login(c, "hr@corp.local", "recruiter")
        w = {"concept_understanding": 25, "logic": 20, "delivery": 15, "attitude": 10, "job_expertise": 30, "code_quality": 0}
        url = f"{API}/admin/jobs/{job.id}/weights"
        r = await c.put(url, json={"weights": {**w, "logic": 25}})
        assert r.status_code == 422 and r.json()["error"]["code"] == "WEIGHTS_SUM_INVALID" and r.json()["error"]["details"]["needed"] == -5
        cq = await c.put(url, json={"weights": {**w, "job_expertise": 20, "code_quality": 10}})  # 코테 OFF 인데 코드 품질
        assert cq.status_code == 422
        assert (await c.put(url, json={"weights": w, "cutoff_score": 120})).status_code == 422
        assert (await c.put(url, json={"weights": w, "cutoff_score": 50, "cutoff_margin": 25})).status_code == 422
        async with rest.sm() as s:
            assert (await s.get(Application, app.id)).ai_pass_prediction.value == "unavailable"
        # 합격선 70, 마진 5 → 72 는 경계. 합격선을 60 으로 낮추면 합격권 (점수 자체는 불변)
        assert (await c.put(url, json={"weights": w, "cutoff_score": 70, "cutoff_margin": 5})).status_code == 200
        async with rest.sm() as s:
            assert (await s.get(Application, app.id)).ai_pass_prediction.value == "borderline"
        assert (await c.put(url, json={"weights": w, "cutoff_score": 60, "cutoff_margin": 5, "gaze_penalty_enabled": True})).json()["gaze_penalty_enabled"]
        async with rest.sm() as s:
            a = await s.get(Application, app.id)
            assert a.ai_pass_prediction.value == "likely_pass" and float(a.ai_total_score) == 72.0
        rules = await c.put(f"{API}/admin/jobs/{job.id}/followup-rules", json={"max_followups": 4, "trigger_ambiguous": False})
        assert rules.json()["max_followups"] == 4 and rules.json()["trigger_ambiguous"] is False
        assert (await c.put(f"{API}/admin/jobs/{job.id}/followup-rules", json={"max_followups": 5})).status_code == 422


async def test_publish_validation_pool_and_lifecycle(rest):
    async with rest.client() as c:
        await staff(rest, c)
        j = (await c.post(f"{API}/admin/jobs", json={"title": "공고"})).json()
        pub = f"{API}/admin/jobs/{j['id']}/publish"
        r = await c.post(pub)
        assert r.status_code == 422 and r.json()["error"]["code"] == "PUBLISH_VALIDATION"
        assert set(r.json()["error"]["details"]["missing"]) == {"job_category", "headcount", "deadline_at", "duties", "requirements"}
        await c.put(f"{API}/admin/jobs/{j['id']}", json={**FULL, "deadline_at": (utcnow() - timedelta(days=1)).isoformat()})
        assert "deadline_at" in (await c.post(pub)).json()["error"]["details"]["missing"]  # 과거 마감일
        await c.put(f"{API}/admin/jobs/{j['id']}", json={"deadline_at": FULL["deadline_at"], "coding_test_enabled": True})
        off = await c.post(pub)  # 샌드박스가 꺼져 있으면 코딩테스트 공고는 게시할 수 없다
        assert off.status_code == 422 and off.json()["error"]["code"] == "SANDBOX_DISABLED"
        assert (await c.get(f"{API}/admin/system/metrics")).json()["sandbox_enabled"] is False
        from tests.fakes import FakeSandbox

        rest.app.state.settings.sandbox_enabled = True
        rest.app.state.services.sandbox = FakeSandbox()
        assert (await c.get(f"{API}/admin/system/metrics")).json()["sandbox_enabled"] is True
        assert "coding_test_time_limit_sec" in (await c.post(pub)).json()["error"]["details"]["missing"]
        await c.put(f"{API}/admin/jobs/{j['id']}", json={"coding_test_enabled": False})
        pool = await c.post(pub)
        assert pool.json()["error"]["code"] == "QUESTION_POOL_INSUFFICIENT" and pool.json()["error"]["details"] == {"manual": 0, "bank": 0, "needed": 10}
        await c.put(f"{API}/admin/jobs/{j['id']}/questions", json={"items": [{"text": f"직접 질문 {i} 입니다"} for i in range(4)]})
        async with rest.sm() as s:  # 뱅크 후보 6개 → 합 10
            s.add_all([JobQuestion(job_id=uuid.UUID(j["id"]), source="ai_bank", text=f"뱅크 질문 {i} 입니까?") for i in range(6)])
            await s.commit()
        ok = await c.post(pub)
        assert ok.status_code == 200 and ok.json()["status"] == "open"
        assert (await c.post(pub)).status_code == 200  # 멱등
        # 지원자 화면에 노출
        assert (await c.get(f"{API}/admin/jobs", params={"status": "open"})).json()["total"] == 1
        closed = await c.post(f"{API}/admin/jobs/{j['id']}/close")
        assert closed.json()["status"] == "closed"
        assert (await c.post(f"{API}/admin/jobs/{j['id']}/close")).status_code == 409  # 재오픈/중복 불가
        assert (await c.put(f"{API}/admin/jobs/{j['id']}", json={"title": "수정"})).json()["error"]["code"] == "JOB_CLOSED"
    async with rest.client() as other:  # 타사 접근
        await rest.company_with_recruiter("타사", "o@corp.local")
        await rest.login(other, "o@corp.local", "recruiter")
        for m, p in (("get", ""), ("put", ""), ("post", "/publish"), ("get", "/question-bank")):
            r = await getattr(other, m)(f"{API}/admin/jobs/{j['id']}{p}", **({"json": {"title": "x"}} if m == "put" else {}))
            assert r.status_code == 404, (m, p)
        assert (await other.get(f"{API}/admin/jobs")).json()["total"] == 0


async def test_question_bank_generation_filters_invalid_and_reports_status(rest):
    topics = ["Redis 캐시 전략을 선택한 기준은 무엇인가요?", "장애가 났을 때 원인을 찾은 과정을 설명해 주세요.", "팀원과 의견이 다를 때 어떻게 조율하셨나요?",
              "데이터베이스 인덱스를 설계한 경험을 말씀해 주세요.", "배포 자동화를 도입한 이유가 무엇이었나요?", "코드 리뷰에서 가장 중요하게 보는 기준은 무엇인가요?"]
    good = [{"question": q, "category": "기술"} for q in topics]
    bad = [{"question": "결혼 계획이 있으신가요?", "category": "인성"}, {"question": "설명입니다.", "category": "기술"}]
    rest.llm.script.append(json.dumps({"items": good + bad + [good[0]]}, ensure_ascii=False))  # 금칙어·형식 위반·중복 포함
    async with rest.client() as c:
        await staff(rest, c)
        j = (await c.post(f"{API}/admin/jobs", json={"title": "공고"})).json()
        url = f"{API}/admin/jobs/{j['id']}/question-bank"
        assert (await c.post(url + "/generate")).json()["error"]["code"] == "JD_REQUIRED"
        await c.put(f"{API}/admin/jobs/{j['id']}", json=FULL)
        assert (await c.post(url + "/generate")).status_code == 202

        async def done():
            return (await c.get(url)).json()["status"] in ("done", "failed")

        await wait_until(done)
        bank = (await c.get(url)).json()
        assert bank["status"] == "done" and len(bank["items"]) == 6 and all("결혼" not in i["text"] for i in bank["items"])
        assert all(i["order_no"] is None for i in bank["items"])
        # 재생성은 후보만 교체하고 직접 등록 질문은 유지
        await c.put(f"{API}/admin/jobs/{j['id']}/questions", json={"items": [{"text": "직접 등록한 질문입니다 설명해 주세요"}]})
        rest.llm.script.append(json.dumps({"items": good[:2]}, ensure_ascii=False))
        assert (await c.post(url + "/generate")).status_code == 202
        await wait_until(lambda: _bank_count(c, url, 2))
        assert len((await c.get(f"{API}/admin/jobs/{j['id']}")).json()["questions"]) == 1


async def _bank_count(c, url, n):  # noqa: ANN001
    d = (await c.get(url)).json()
    return d["status"] == "done" and len(d["items"]) == n


async def test_question_bank_failure_and_interview_busy(rest):
    from app.models import InterviewSession
    from app.models.enums import SessionState

    async with rest.client() as c:
        co, _ = await staff(rest, c)
        j = (await c.post(f"{API}/admin/jobs", json=FULL)).json()
        url = f"{API}/admin/jobs/{j['id']}/question-bank"
        rest.llm.default = "not json"
        assert (await c.post(url + "/generate")).status_code == 202

        async def failed():
            return (await c.get(url)).json()["status"] == "failed"

        await wait_until(failed)
        assert (await c.get(url)).json()["message"]
        # 면접이 진행 중이면 503
        user = await rest.applicant()
        job = (await rest.sm().__aenter__()) if False else None  # noqa: F841
        app = Application(user_id=user.id, job_id=uuid.UUID(j["id"]), status=ApplicationStatus.INTERVIEWING, consent_at=utcnow())
        await rest.add(app)
        sess = InterviewSession(application_id=app.id, state=SessionState.IN_PROGRESS)
        await rest.add(sess)
        busy = await c.post(url + "/generate")
        assert busy.status_code == 503 and busy.json()["error"]["code"] == "BUSY_INTERVIEW_ACTIVE"


# ── 비교 ────────────────────────────────────────────────────────────────────
async def done_applicant(rest, job, email, name, score, with_scores=True):
    from app.models import ReportScore
    from app.models.enums import Criterion

    user = await rest.applicant(email, name)
    app, sess, turn = await rest.finished_interview(user, job, score=score)
    async with rest.sm() as s:
        a = await s.get(Application, app.id)
        a.status = ApplicationStatus.REPORT_READY
        rep = EvaluationReport(session_id=sess.id, status=ReportStatus.DONE, total_score=score, strengths=[{"rank": 1, "title": f"{name} 강점", "detail": "d", "evidence": []}],
                               improvements=[{"rank": 1, "title": f"{name} 개선", "detail": "d", "evidence": []}], gaze_away_ratio=0.05)
        s.add(rep)
        await s.flush()
        if with_scores:
            for c in ("concept_understanding", "logic", "delivery", "attitude", "job_expertise"):
                s.add(ReportScore(report_id=rep.id, turn_id=None, criterion=Criterion(c), score=score))
        await s.commit()
    return app


async def test_compare_rules_and_payload(rest):
    async with rest.client() as c:
        co, hr = await staff(rest, c)
        j1, j2 = await rest.job(co.id, "J1"), await rest.job(co.id, "J2")
        a = await done_applicant(rest, j1, "a@corp.local", "가나", 82.5)
        b = await done_applicant(rest, j1, "b@corp.local", "다라", 71)
        x = await done_applicant(rest, j2, "x@corp.local", "타공고", 60)
        queued = await rest.finished_interview(await rest.applicant("q@corp.local", "대기"), j1)
        r = await c.get(f"{API}/admin/applicants/compare", params={"ids": f"{a.id},{b.id}"})
        assert r.status_code == 200
        body = r.json()
        assert body["job_title"] == "J1" and body["axes"] == ["concept_understanding", "logic", "delivery", "attitude", "job_expertise"]
        assert [p["name"] for p in body["applicants"]] == ["가나", "다라"] and body["applicants"][0]["criteria"]["logic"] == 82.5
        assert body["applicants"][0]["strengths"] == ["가나 강점"] and body["applicants"][0]["gaze_away_ratio"] == 0.05
        assert "code_quality" not in body["axes"]
        bad = lambda ids: c.get(f"{API}/admin/applicants/compare", params={"ids": ids})  # noqa: E731
        assert (await bad(str(a.id))).status_code == 400
        assert (await bad(f"{a.id},{a.id}")).status_code == 400
        assert (await bad(f"{a.id},nope")).status_code == 400
        assert (await bad(f"{a.id},{b.id},{x.id},{queued[0].id}")).status_code == 400
        mixed = await bad(f"{a.id},{x.id}")
        assert mixed.status_code == 400 and mixed.json()["error"]["code"] == "COMPARE_INVALID_SELECTION"
        nr = await bad(f"{a.id},{queued[0].id}")
        assert nr.status_code == 409 and nr.json()["error"]["details"]["application_ids"] == [str(queued[0].id)]
        assert (await bad(f"{a.id},{uuid.uuid4()}")).status_code == 404
    async with rest.client() as other:
        await rest.company_with_recruiter("타사", "o@corp.local")
        await rest.login(other, "o@corp.local", "recruiter")
        assert (await other.get(f"{API}/admin/applicants/compare", params={"ids": f"{a.id},{b.id}"})).status_code == 404


# ── 결정 · 메일 ─────────────────────────────────────────────────────────────
class FakeMailer:
    def __init__(self):
        self.sent, self.fail = [], None

    async def send(self, to, subject, body):  # noqa: ANN001, ANN201
        if self.fail:
            raise self.fail
        self.sent.append((to, subject, body))


async def test_decision_lifecycle_audit_and_notified_guard(rest):
    mailer = FakeMailer()
    rest.app.state.services.mailer = mailer
    async with rest.client() as c:
        co, hr = await staff(rest, c)
        job = await rest.job(co.id)
        a = await done_applicant(rest, job, "a@corp.local", "가나", 80)
        pending = await rest.finished_interview(await rest.applicant("q@corp.local", "대기"), job)
        url = lambda i: f"{API}/admin/applications/{i}/decision"  # noqa: E731
        assert (await c.post(url(pending[0].id), json={"decision": "pass"})).json()["error"]["code"] == "REPORT_NOT_READY"
        r = await c.post(url(a.id), json={"decision": "pass", "memo": "기술 면접 우수"})
        assert r.status_code == 200 and r.json()["final_decision"] == "pass" and r.json()["decided_at"]
        # 결정 전 메일 불일치 / 템플릿 일치
        assert (await c.post(f"{API}/admin/applications/{a.id}/mail", json={"template": "fail"})).json()["error"]["code"] == "DECISION_MISMATCH"
        sent = await c.post(f"{API}/admin/applications/{a.id}/mail", json={"template": "pass"})
        assert sent.status_code == 200 and sent.json()["result_notified_at"]
        to, subject, body = mailer.sent[0]
        assert to == "a@corp.local" and "합격" in subject and "가나" in body
        assert "80" not in body and "합격권" not in body and "점수" not in body  # AI 점수·예상 합불 비노출
        # 안내 후 변경은 확인 필요
        g = await c.post(url(a.id), json={"decision": "fail"})
        assert g.status_code == 409 and g.json()["error"]["code"] == "DECISION_ALREADY_NOTIFIED"
        assert (await c.post(url(a.id), json={"decision": "pass"})).status_code == 200  # 같은 값이면 확인 불필요(멱등)
        ok = await c.post(url(a.id), json={"decision": "fail", "acknowledge_notified": True})
        assert ok.json()["final_decision"] == "fail"
        cancel = await c.post(url(a.id), json={"decision": "pending", "acknowledge_notified": True})
        assert cancel.json()["final_decision"] == "pending" and cancel.json()["decided_at"] is None
        async with rest.sm() as s:
            logs = (await s.execute(select(AuditLog).where(AuditLog.target_id == a.id).order_by(AuditLog.created_at))).scalars().all()
            actions = [l.action for l in logs if l.action in ("decide", "change_decision", "send_mail")]
            assert actions[0] == "decide" and "change_decision" in actions and "send_mail" in actions
            assert "기술 면접" not in json.dumps([l.detail for l in logs], ensure_ascii=False)  # 감사 로그에 자유 텍스트 없음
            notes = (await s.execute(select(RecruiterNote).where(RecruiterNote.application_id == a.id))).scalars().all()
            assert [n.body for n in notes] == ["기술 면접 우수"]
        assert (await c.post(url(a.id), json={"decision": "maybe"})).status_code == 422


async def test_schedule_mail_validation_and_smtp_errors(rest):
    from app.services.mailer import MailNotConfigured, MailSendFailed

    mailer = FakeMailer()
    rest.app.state.services.mailer = mailer
    async with rest.client() as c:
        co, _ = await staff(rest, c)
        a = await done_applicant(rest, await rest.job(co.id), "a@corp.local", "가나", 80)
        m = f"{API}/admin/applications/{a.id}/mail"
        assert (await c.post(m, json={"template": "schedule"})).status_code == 422
        assert (await c.post(m, json={"template": "schedule", "schedule_link": "javascript:alert(1)"})).status_code == 422
        ok = await c.post(m, json={"template": "schedule", "schedule_link": "https://cal.corp.local/x"})
        assert ok.status_code == 200 and ok.json()["result_notified_at"] is None and "https://cal.corp.local/x" in mailer.sent[0][2]
        mailer.fail = MailNotConfigured()
        assert (await c.post(m, json={"template": "schedule", "schedule_link": "https://a.b/c"})).json()["error"]["code"] == "MAIL_NOT_CONFIGURED"
        mailer.fail = MailSendFailed("x")
        assert (await c.post(m, json={"template": "schedule", "schedule_link": "https://a.b/c"})).status_code == 502
    async with rest.client() as other:
        await rest.company_with_recruiter("타사", "o@corp.local")
        await rest.login(other, "o@corp.local", "recruiter")
        assert (await other.post(m, json={"template": "schedule", "schedule_link": "https://a.b/c"})).status_code == 404
        assert (await other.post(f"{API}/admin/applications/{a.id}/decision", json={"decision": "pass"})).status_code == 404


_ = (FinalDecision, JobPosting, JobStatus, QuestionBankStatus)


async def test_background_and_applicant_activity_do_not_invalidate_admins_updated_at(rest):
    """질문 뱅크 상태 변경·지원자의 공고 조회(view_count)가 담당자의 다음 저장을 STALE_UPDATE 로 막으면 안 된다 (E2E 에서 발견한 회귀)."""
    rest.llm.default = "not json"
    async with rest.client() as c:
        co, _ = await staff(rest, c)
        j = (await c.post(f"{API}/admin/jobs", json=FULL)).json()
        url = f"{API}/admin/jobs/{j['id']}/question-bank"
        assert (await c.post(url + "/generate")).status_code == 202

        async def failed():
            return (await c.get(url)).json()["status"] == "failed"

        await wait_until(failed)
        await rest.add(*[])
        async with rest.client() as ap:
            await rest.applicant()
            await rest.login(ap, "a@corp.local")
            async with rest.sm() as s:
                row = await s.get(JobPosting, uuid.UUID(j["id"]))
                row.status = JobStatus.OPEN
                await s.commit()
            j0 = (await c.get(f"{API}/admin/jobs/{j['id']}")).json()
            assert (await ap.get(f"{API}/jobs/{j['id']}")).status_code == 200
        ok = await c.put(f"{API}/admin/jobs/{j['id']}", json={"title": "수정된 제목", "updated_at": j0["updated_at"]})
        assert ok.status_code == 200, ok.text
        stale = await c.put(f"{API}/admin/jobs/{j['id']}", json={"title": "또 수정", "updated_at": j0["updated_at"]})
        assert stale.status_code == 409  # 진짜 동시 편집은 여전히 감지


async def test_job_templates_save_apply_and_isolation(rest):
    async with rest.client() as c:
        await staff(rest, c)
        j = (await c.post(f"{API}/admin/jobs", json={**FULL, "coding_test_enabled": True, "coding_test_time_limit_sec": 3600})).json()
        await c.put(f"{API}/admin/jobs/{j['id']}/questions", json={"items": [{"text": "자기소개를 해 주세요", "time_limit_sec": 90}, {"text": "Redis 를 쓴 이유는?"}]})
        await c.put(f"{API}/admin/jobs/{j['id']}/followup-rules", json={"max_followups": 1, "trigger_ambiguous": True, "trigger_contradiction": False,
                                                                       "trigger_stt_unclear": True, "guardrail_strict": True})
        t = await c.post(f"{API}/admin/job-templates", json={"job_id": j["id"], "name": "백엔드 기본"})
        assert t.status_code == 201 and t.json()["question_count"] == 2 and t.json()["coding_test_enabled"] is True
        dup = await c.post(f"{API}/admin/job-templates", json={"job_id": j["id"], "name": "백엔드 기본"})
        assert dup.status_code == 409 and dup.json()["error"]["code"] == "TEMPLATE_NAME_EXISTS"
        # 템플릿 행은 공고 목록·대시보드에 섞이지 않는다
        assert (await c.get(f"{API}/admin/jobs")).json()["total"] == 1
        assert [x["name"] for x in (await c.get(f"{API}/admin/job-templates")).json()] == ["백엔드 기본"]

        new = (await c.post(f"{API}/admin/jobs", json={"title": "새 공고", "deadline_at": FULL["deadline_at"], "headcount": 5})).json()
        applied = await c.post(f"{API}/admin/jobs/{new['id']}/from-template/{t.json()['id']}")
        assert applied.status_code == 200
        a = applied.json()
        assert a["title"] == "백엔드 개발자" and a["duties"] == FULL["duties"] and a["coding_test_enabled"] is True
        assert [q["text"] for q in a["questions"]] == ["자기소개를 해 주세요", "Redis 를 쓴 이유는?"] and a["questions"][0]["time_limit_sec"] == 90
        assert a["followup_rules"]["max_followups"] == 1 and a["followup_rules"]["trigger_contradiction"] is False
        assert a["headcount"] == 5 and a["status"] == "draft"  # 마감일·정원·상태는 건드리지 않는다
        # 원본과 독립: 새 공고 질문을 바꿔도 템플릿은 그대로
        await c.put(f"{API}/admin/jobs/{new['id']}/questions", json={"items": [{"text": "전혀 다른 질문입니다"}]})
        assert (await c.get(f"{API}/admin/job-templates")).json()[0]["question_count"] == 2
        assert (await c.post(f"{API}/admin/jobs/{new['id']}/from-template/{uuid.uuid4()}")).status_code == 404
    async with rest.client() as o:
        await staff(rest, o, "타사", "other@corp.local")
        assert (await o.get(f"{API}/admin/job-templates")).json() == []
        other = (await o.post(f"{API}/admin/jobs", json={"title": "타사 공고"})).json()
        assert (await o.post(f"{API}/admin/jobs/{other['id']}/from-template/{t.json()['id']}")).status_code == 404


async def test_template_cannot_overwrite_published_job(rest):
    async with rest.client() as c:
        co, _hr = await staff(rest, c)
        src = (await c.post(f"{API}/admin/jobs", json=FULL)).json()
        t = (await c.post(f"{API}/admin/job-templates", json={"job_id": src["id"], "name": "t"})).json()
        live = await rest.job(co.id, "게시 중")
        r = await c.post(f"{API}/admin/jobs/{live.id}/from-template/{t['id']}")
        assert r.status_code == 409 and r.json()["error"]["code"] == "JOB_NOT_DRAFT"
