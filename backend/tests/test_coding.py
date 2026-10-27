"""코딩테스트: 채점 집계 · REST · 접근 제어 · 코드 꼬리질문 · code_quality 점수."""
from __future__ import annotations

import asyncio

import pytest

from app.coding.analysis import analyze_source, parse_python_tools, quality_score
from app.coding.judge import RunResult, case_verdict, judge, normalize, overall
from app.coding.problems import PROBLEMS, pick_problem
from app.models import CodeSubmission, InterviewSession, JobPosting
from app.models.enums import SessionState
from tests.conftest import API
from tests.fakes import FakeSandbox
from tests.rest_env import rest, wait_until  # noqa: F401


# ── 순수 로직 ────────────────────────────────────────────────────────────────
def test_normalize_ignores_trailing_whitespace_and_crlf():
    assert normalize("a  \r\nb\n\n") == "a\nb"


@pytest.mark.parametrize("r,expected,verdict", [
    (RunResult(0, "1 2\n"), "1 2", "AC"), (RunResult(0, "1 3\n"), "1 2", "WA"), (RunResult(1, "", "err"), "1", "RE"),
    (RunResult(-9, timed_out=True), "1", "TLE"), (RunResult(137, oom=True), "1", "MLE"), (RunResult(0, "x", truncated=True), "x", "OLE"),
    (RunResult(1, compile_error=True), "x", "CE"),
])
def test_case_verdict(r, expected, verdict):
    assert case_verdict(r, expected) == verdict


def test_overall_picks_most_severe_and_requires_all_ac():
    assert overall(["AC", "AC"]) == "AC"
    assert overall(["AC", "WA"]) == "WA"
    assert overall(["WA", "TLE", "AC"]) == "TLE"
    assert overall(["WA", "CE"]) == "CE"


async def test_judge_stops_at_compile_error_and_hides_hidden_case_io():
    p = PROBLEMS[0]
    ok = await judge(FakeSandbox(), "python", "print()", p.cases, visible=p.samples, time_limit_s=3)
    assert ok.verdict == "AC" and len(ok.cases) == len(p.cases)
    assert all(c.stdout for c in ok.cases if c.visible) and not any(c.stdout for c in ok.cases if not c.visible)  # 비공개 케이스 출력은 담지 않는다
    sb = FakeSandbox()
    ce = await judge(sb, "python", "SYNTAX", p.cases, visible=p.samples, time_limit_s=3)
    assert ce.verdict == "CE" and len(ce.cases) == 1 and sb.calls == 1 and "SyntaxError" in ce.compile_log


def test_problem_bank_is_valid_and_pick_is_deterministic():
    import uuid

    for p in PROBLEMS:
        assert 2 <= len(p.cases) <= 10 and p.samples <= len(p.cases)
    sid = uuid.uuid4()
    assert pick_problem(sid) is pick_problem(sid)


async def test_analysis_python_ast_fallback_and_tool_parsing():
    a = await analyze_source(FakeSandbox(), "python", "def f(x):\n    if x:\n        return 1\n    return 2\n")
    assert a["tool"] == "ast" and a["functions"] == 1 and a["max_complexity"] == 2
    assert (await analyze_source(FakeSandbox(), "python", "def (:")).get("syntax_error") is True
    js = await analyze_source(FakeSandbox(), "javascript", "function a(){ if(1){ } }\nconst b=()=>1;")
    assert js["functions"] == 2 and js["max_nesting"] == 2
    assert parse_python_tools('[{"code":"E501"}]\n@@\n{"main.py":[{"complexity":4}]}\n@@\n{"main.py":{"mi":72.5}}') == {
        "lint_issues": 1, "lint_codes": ["E501"], "max_complexity": 4, "maintainability": 72.5}
    assert parse_python_tools("garbage") is None


def test_quality_score_weights_correctness_over_style():
    full = [{"verdict": "AC"}] * 4
    assert quality_score("AC", full, {}) == 100.0
    assert quality_score("WA", [{"verdict": "AC"}, {"verdict": "WA"}], {}) == pytest.approx(65.0)  # 0.7*50 + 0.3*100
    assert quality_score("AC", full, {"lint_issues": 20, "max_complexity": 40}) < quality_score("AC", full, {})
    assert quality_score("CE", [{"verdict": "CE"}], {}) == pytest.approx(30.0)  # 컴파일 오류: 정답률 0 + 스타일만
    assert quality_score(None, None, None) == pytest.approx(30.0)


# ── REST ─────────────────────────────────────────────────────────────────────
async def _coding_session(rest, *, coding=True, state=SessionState.CODING):
    co, _hr = await rest.company_with_recruiter()
    job = await rest.job(co.id, coding_test_enabled=coding, coding_test_time_limit_sec=3600 if coding else None)
    user = await rest.applicant()
    app, sess, _turn = await rest.finished_interview(user, job)
    async with rest.sm() as s:
        row = await s.get(InterviewSession, sess.id)
        row.state = state
        await s.commit()
    rest.app.state.settings.sandbox_enabled = True
    rest.app.state.services.sandbox = FakeSandbox()
    return job, user, app, sess


async def _poll_result(c, sid):
    async def done():
        return (await c.get(f"{API}/sessions/{sid}/code/result")).json()["status"] == "done"

    await wait_until(done, 10)
    return (await c.get(f"{API}/sessions/{sid}/code/result")).json()


async def test_problem_run_submit_result_flow(rest):
    _job, _user, _app, sess = await _coding_session(rest)
    async with rest.client() as c:
        await rest.login(c, "a@corp.local")
        assert (await c.get(f"{API}/sessions/{sess.id}/code/result")).json() == {**(await c.get(f"{API}/sessions/{sess.id}/code/result")).json(), "status": "none"}
        p = (await c.get(f"{API}/sessions/{sess.id}/code/problem")).json()
        assert p["title"] and len(p["examples"]) == 2 and {x["id"] for x in p["languages"]} == {"python", "java", "javascript"}
        assert p["submitted"] is False and p["time_limit_sec"] == 3600 and p["exec_time_limit_sec"] == 3
        # 샘플 실행: 오답 → WA, 공개 케이스 출력만 담는다
        run = (await c.post(f"{API}/sessions/{sess.id}/code/run", json={"language": "python", "source": "WRONG"})).json()
        assert run["verdict"] == "WA" and len(run["cases"]) == 2 and run["cases"][0]["stdout"].strip() == "wrong"
        assert (await c.post(f"{API}/sessions/{sess.id}/code/run", json={"language": "python", "source": "ok"})).json()["verdict"] == "AC"
        assert (await c.post(f"{API}/sessions/{sess.id}/code/run", json={"language": "cobol", "source": "x"})).status_code == 422
        assert (await c.post(f"{API}/sessions/{sess.id}/code/run", json={"language": "python", "source": ""})).status_code == 422
        # 제출 → 202 → 결과 polling
        sub = await c.post(f"{API}/sessions/{sess.id}/code/submit", json={"language": "python", "source": "ok"})
        assert sub.status_code == 202
        res = await _poll_result(c, sess.id)
        assert res["verdict"] == "AC" and len(res["cases"]) == len(pick_for(sess.id).cases)
        assert res["source_code"] is None and res["static_analysis"] is None  # 지원자 응답에는 코드·분석을 되돌리지 않는다
        assert not any(x["stdout"] for x in res["cases"] if not x["visible"])
        again = await c.post(f"{API}/sessions/{sess.id}/code/submit", json={"language": "python", "source": "ok"})
        assert again.status_code == 409 and again.json()["error"]["code"] == "CODE_ALREADY_SUBMITTED"
        assert (await c.post(f"{API}/sessions/{sess.id}/code/run", json={"language": "python", "source": "ok"})).status_code == 409
    async with rest.sm() as s:
        row = (await s.execute(CodeSubmission.__table__.select())).first()
        assert row is not None
    # 저장된 소스는 암호화 컬럼이라 원문이 DB 행에 평문으로 있지 않다
    import sqlalchemy as sa

    async with rest.sm() as s:
        raw = (await s.execute(sa.text("select source_code from code_submissions"))).scalar_one()
        assert raw != "ok"


def pick_for(sid):  # noqa: ANN001, ANN201
    return pick_problem(sid)


async def test_submit_verdicts_and_staff_view(rest):
    job, _user, _app, sess = await _coding_session(rest)
    async with rest.client() as c:
        await rest.login(c, "a@corp.local")
        await c.post(f"{API}/sessions/{sess.id}/code/submit", json={"language": "python", "source": "LOOP"})
        res = await _poll_result(c, sess.id)
        assert res["verdict"] == "TLE"
    async with rest.client() as hr:
        await rest.login(hr, "hr@corp.local", "recruiter")
        r = (await hr.get(f"{API}/sessions/{sess.id}/code/result")).json()
        assert r["source_code"] == "LOOP" and r["static_analysis"]["tool"] == "ast"  # 담당자는 코드와 정적 분석을 볼 수 있다
    async with rest.client() as other:
        await rest.company_with_recruiter("타사", "o@corp.local")
        await rest.login(other, "o@corp.local", "recruiter")
        assert (await other.get(f"{API}/sessions/{sess.id}/code/result")).status_code == 404
    async with rest.client() as stranger:
        await rest.applicant("b@corp.local", "이다른")
        await rest.login(stranger, "b@corp.local")
        for path in ("problem", "result"):
            assert (await stranger.get(f"{API}/sessions/{sess.id}/code/{path}")).status_code == 404
        assert (await stranger.post(f"{API}/sessions/{sess.id}/code/run", json={"language": "python", "source": "x"})).status_code == 404


async def test_coding_guards(rest):
    # 질문이 끝나기 전(상태 in_progress)에는 문제를 줄 수 없다
    _j, _u, _a, sess = await _coding_session(rest, state=SessionState.IN_PROGRESS)
    async with rest.client() as c:
        await rest.login(c, "a@corp.local")
        r = await c.get(f"{API}/sessions/{sess.id}/code/problem")
        assert r.status_code == 409 and r.json()["error"]["code"] == "CODING_NOT_AVAILABLE"
        assert (await c.post(f"{API}/sessions/{sess.id}/code/submit", json={"language": "python", "source": "x"})).status_code == 409
    # 샌드박스 비활성
    rest.app.state.settings.sandbox_enabled = False
    async with rest.client() as c:
        await rest.login(c, "a@corp.local")
        r = await c.get(f"{API}/sessions/{sess.id}/code/problem")
        assert r.status_code == 503 and r.json()["error"]["code"] == "SANDBOX_DISABLED"


async def test_job_without_coding_test_has_no_problem(rest):
    _j, _u, _a, sess = await _coding_session(rest, coding=False)
    async with rest.client() as c:
        await rest.login(c, "a@corp.local")
        assert (await c.get(f"{API}/sessions/{sess.id}/code/problem")).status_code == 404


async def test_report_mixes_code_quality_into_total_with_its_weight(rest):
    from sqlalchemy import select

    from app.models import EvaluationReport, ReportScore
    from app.models.base import utcnow
    from app.models.enums import Verdict
    from tests.test_worker_report import eval_json, make_session, narrative_json, worker

    _co, _hr, _user, _job, app, sess, turns = await make_session(
        rest, cutoff=60, weights=dict(concept_understanding=10, logic=10, delivery=10, attitude=10, job_expertise=10, code_quality=50))
    await rest.add(CodeSubmission(session_id=sess.id, language="python", source_code="print()", verdict=Verdict.AC, runtime_ms=12, submitted_at=utcnow(),
                                  case_results=[{"index": i, "verdict": "AC"} for i in range(1, 5)], static_analysis={"lint_issues": 0, "max_complexity": 2}))
    rest.llm.script.extend([
        eval_json((5, 4, 4, 4, 3), ref=f"turn:{turns[0].id}", highlight={"kind": "good", "quote": "조회 응답 시간을 800ms에서 200ms로 줄였습니다", "reason": "정량적 성과를 제시"}),
        eval_json((2, 2, 2, 2, 2), quote="그냥 제가 참았습니다", ref=f"turn:{turns[1].id}", highlight={"kind": "bad", "quote": "별로 한 게 없습니다", "reason": "구체성이 없음"}),
        narrative_json(f"turn:{turns[0].id}").replace("그냥 제가 참았습니다", "Redis 캐시를 도입해")])
    assert await worker(rest).run_once() == "done"
    async with rest.sm() as s:
        rep = (await s.execute(select(EvaluationReport).where(EvaluationReport.session_id == sess.id))).scalar_one()
        overall = {x.criterion.value: float(x.score) for x in (await s.execute(select(ReportScore).where(ReportScore.report_id == rep.id))).scalars() if x.turn_id is None}
        assert overall["code_quality"] == 100.0 and len(overall) == 6
        assert float(rep.total_score) == 80.0  # 0.1*(70+60+60+60+50) + 0.5*100
        assert rep.weights_snapshot["effective_weights"]["code_quality"] == 50.0
        cq = next(x for x in (await s.execute(select(ReportScore).where(ReportScore.report_id == rep.id))).scalars() if x.criterion.value == "code_quality")
        assert "코딩테스트" in cq.comment and "4/4" in cq.comment
    _ = (app,)
