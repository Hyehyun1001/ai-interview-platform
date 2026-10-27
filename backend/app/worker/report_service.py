"""세션 1건의 리포트 생성 (TRD §3.4 report_chain, §6.3). DB 읽기 → LLM 채점(턴별) → 집계 → 한 트랜잭션으로 저장.

LLM 호출 중에는 DB 트랜잭션을 열어 두지 않고, 저장은 마지막에 한 번에 한다 → 도중에 실패해도 반쪽짜리 리포트가 남지 않는다.
로그에는 식별자와 개수만 남기며 답변 원문·인용·점수 코멘트는 남기지 않는다 (NFR-S1).
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.runnables import Runnable
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.chains.report_chain import CRITERIA as EVAL_CRITERIA
from app.ai.chains.report_chain import evaluate_turn, write_narrative
from app.ai.chains.report_prompts import CRITERION_LABELS, RUBRIC_VERSION, TurnEvalInputs
from app.ai.guardrail import GuardrailEventSink
from app.models import (Application, EvalWeight, EvaluationReport, GazeEvent, Highlight, InterviewSession, InterviewTurn, JobPosting,
                        Notification, ReportScore, User, VoiceTimeline)
from app.models.base import utcnow
from app.models.enums import (AiPassPrediction, ApplicationStatus, Criterion, HighlightKind, ReportStatus, TimelineKind, UserRole)
from app.worker import scoring

log = logging.getLogger("app.worker.report")

MIN_ANSWER_CHARS = 5  # 이보다 짧은 전사는 STT 실패/무응답으로 보고 채점에서 제외한다 (시스템 문제로 지원자를 감점하지 않기 위해)
DEFAULT_WEIGHTS = {"concept_understanding": 25, "logic": 20, "delivery": 15, "attitude": 10, "job_expertise": 30, "code_quality": 0}


class ReportNotPossible(Exception):
    """채점할 수 있는 턴이 하나도 없다 — 재시도해도 같으므로 즉시 failed."""


@dataclass
class _TurnData:
    id: uuid.UUID
    turn_no: int
    question: str
    answer: str
    duration_ms: int
    gaze: list[tuple[int, int]]

    @property
    def ref(self) -> str:
        return f"turn:{self.id}"


@dataclass
class _Loaded:
    job_title: str
    jd: str
    weights: dict[str, int]
    gaze_penalty_enabled: bool
    cutoff: float | None
    margin: float
    turns: list[_TurnData] = field(default_factory=list)


async def _load(sm: async_sessionmaker, session_id: uuid.UUID) -> _Loaded:
    async with sm() as db:
        sess = await db.get(InterviewSession, session_id)
        app = await db.get(Application, sess.application_id)
        job = await db.get(JobPosting, app.job_id)
        w = (await db.execute(select(EvalWeight).where(EvalWeight.job_id == job.id))).scalar_one_or_none()
        turns = (await db.execute(select(InterviewTurn).where(InterviewTurn.session_id == session_id).order_by(InterviewTurn.turn_no))).scalars().all()
        gaze = (await db.execute(select(GazeEvent).where(GazeEvent.session_id == session_id))).scalars().all()
        weights = {c: getattr(w, c) for c in DEFAULT_WEIGHTS} if w else dict(DEFAULT_WEIGHTS)
        data = _Loaded(job.title, "\n".join(filter(None, [job.duties, job.requirements])), weights, bool(w and w.gaze_penalty_enabled),
                       float(job.cutoff_score) if job.cutoff_score is not None else None, float(job.cutoff_margin))
        for t in turns:
            dur = t.answer_duration_ms or 0
            data.turns.append(_TurnData(t.id, t.turn_no, t.question_text, (t.answer_text or "").strip(), dur,
                                        [(g.start_ms, g.end_ms) for g in gaze if g.turn_id == t.id]))
        return data


def _turn_summary(td: _TurnData, levels: dict[str, int], comment: str) -> str:
    return f"- ref={td.ref} · 질문: {td.question[:60]} · 점수: " + ", ".join(f"{CRITERION_LABELS[c]} {levels[c] * 20}" for c in levels) + f" · {comment[:80]}"


async def generate_report(sm: async_sessionmaker, llm_factory: Callable[[float], Runnable], session_id: uuid.UUID, *,
                          sink: GuardrailEventSink | None = None, timeout_s: float | None = None, model_name: str = "") -> None:
    """리포트를 생성해 저장한다. LLMUnavailable 은 그대로 올린다(워커가 재시도). 채점 가능한 턴이 없으면 ReportNotPossible."""
    async with sm() as db:
        report = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == session_id))).scalar_one_or_none()
        if report is None:
            report = EvaluationReport(session_id=session_id)
            db.add(report)
        report.status = ReportStatus.RUNNING
        await db.commit()
        report_id = report.id

    data = await _load(sm, session_id)
    scorable = [t for t in data.turns if len(t.answer) >= MIN_ANSWER_CHARS]
    if not scorable:
        raise ReportNotPossible("no scorable turns")

    evals = {}
    for td in scorable:  # 순차 실행: Ollama 는 한 번에 하나만 (메모리·지연 예산)
        ev = await evaluate_turn(llm_factory, TurnEvalInputs(data.job_title, data.jd, td.question, td.answer, td.ref), sink=sink,
                                 timeout_s=timeout_s, session_id=session_id, turn_id=td.id)
        if ev is not None:
            evals[td.id] = ev
    unscored = len(data.turns) - len(evals)
    if not evals:
        raise ReportNotPossible("all turns failed validation")

    by_turn = {td.id: td for td in scorable}
    levels = {tid: {c: getattr(ev, c).level for c in EVAL_CRITERIA} for tid, ev in evals.items()}
    means = scoring.criterion_means(list(levels.values()))
    ratio = scoring.gaze_away_ratio([(t.duration_ms, t.gaze) for t in data.turns])
    penalty = scoring.gaze_penalty(ratio, data.gaze_penalty_enabled)
    total, eff = scoring.total_score(means, data.weights, penalty)
    assert total is not None  # means 가 비어 있지 않으면 effective_weights 가 항상 값을 돌려준다
    prediction = scoring.predict(total, data.cutoff, data.margin)

    narrative = await write_narrative(
        llm_factory, job_title=data.job_title, criteria=means,
        turn_summaries="\n".join(_turn_summary(by_turn[tid], levels[tid], getattr(ev, min(levels[tid], key=levels[tid].get)).comment) for tid, ev in evals.items()),
        excerpts={by_turn[tid].ref: by_turn[tid].answer for tid in evals}, sink=sink, timeout_s=timeout_s, session_id=session_id)
    narrative_fallback = narrative is None
    if narrative is not None:
        summary = narrative.summary
        strengths = [{"rank": i + 1, "title": it.title, "detail": it.detail, "evidence": [e.model_dump() for e in it.evidence]} for i, it in enumerate(narrative.strengths)]
        improvements = [{"rank": i + 1, "title": it.title, "detail": it.detail, "evidence": [e.model_dump() for e in it.evidence]} for i, it in enumerate(narrative.improvements)]
    else:
        summary, s_items, i_items = scoring.fallback_narrative(means, CRITERION_LABELS, total)
        strengths = [{"rank": i + 1, "title": x.title, "detail": x.detail, "evidence": []} for i, x in enumerate(s_items)]
        improvements = [{"rank": i + 1, "title": x.title, "detail": x.detail, "evidence": []} for i, x in enumerate(i_items)]

    async with sm() as db:  # ── 저장: 한 트랜잭션 ──
        report = await db.get(EvaluationReport, report_id)
        # 재생성 대비: 이전 결과 제거 (이 리포트가 만든 행만)
        await db.execute(delete(ReportScore).where(ReportScore.report_id == report_id))
        await db.execute(delete(Highlight).where(Highlight.report_id == report_id))
        await db.execute(delete(VoiceTimeline).where(VoiceTimeline.turn_id.in_([t.id for t in data.turns]),
                                                     VoiceTimeline.kind.in_([TimelineKind.HIGHLIGHT_GOOD, TimelineKind.HIGHLIGHT_BAD])))
        for tid, ev in evals.items():
            td = by_turn[tid]
            quotes = [e.model_dump() for e in ev.evidence]
            for c in EVAL_CRITERIA:
                ce = getattr(ev, c)
                db.add(ReportScore(report_id=report_id, turn_id=tid, criterion=Criterion(c), score=scoring.level_score(ce.level), comment=ce.comment, evidence=quotes))
            if ev.highlight is not None:
                span = scoring.quote_span_ms(td.answer, ev.highlight.quote, td.duration_ms)
                if span is not None:
                    kind = HighlightKind(ev.highlight.kind)
                    worst = min(levels[tid].values())
                    db.add(Highlight(report_id=report_id, turn_id=tid, kind=kind, start_ms=span[0], end_ms=span[1], reason=ev.highlight.reason))
                    db.add(VoiceTimeline(turn_id=tid, start_ms=span[0], end_ms=span[1],
                                         kind=TimelineKind.HIGHLIGHT_GOOD if kind == HighlightKind.GOOD else TimelineKind.HIGHLIGHT_BAD,
                                         text=ev.highlight.quote, ai_comment=ev.highlight.reason,
                                         severity=(3 if worst <= 1 else 2 if worst == 2 else 1) if kind == HighlightKind.BAD else None))
        for c, m in means.items():
            db.add(ReportScore(report_id=report_id, turn_id=None, criterion=Criterion(c), score=round(m, 2),
                               comment=f"{len(evals)}개 질문 평균 (가중치 {eff.get(c, 0):.0f}%)", evidence=None))
        report.status, report.total_score, report.summary = ReportStatus.DONE, total, summary
        report.strengths, report.improvements, report.gaze_away_ratio = strengths, improvements, ratio
        report.weights_snapshot = {"weights": data.weights, "effective_weights": {k: round(v, 2) for k, v in eff.items()},
                                   "gaze_penalty_enabled": data.gaze_penalty_enabled, "gaze_penalty": round(penalty, 2)}
        report.model_info = {"llm": model_name, "rubric": RUBRIC_VERSION, "scored_turns": len(evals), "unscored_turns": unscored,
                             "narrative_fallback": narrative_fallback, "highlight_timing": "estimated_proportional"}
        report.generated_at = utcnow()

        sess = await db.get(InterviewSession, session_id)
        app = await db.get(Application, sess.application_id)
        app.ai_total_score, app.ai_pass_prediction = total, AiPassPrediction(prediction)
        if app.status == ApplicationStatus.INTERVIEW_DONE:
            app.status = ApplicationStatus.REPORT_READY
        job = await db.get(JobPosting, app.job_id)
        staff = (await db.execute(select(User.id).where(User.company_id == job.company_id,
                                                        User.role.in_([UserRole.RECRUITER, UserRole.ADMIN])))).scalars().all()
        for uid in staff:  # 담당자에게 리포트 완료 알림 (식별자만 — 이름·점수는 담지 않는다)
            db.add(Notification(user_id=uid, type="report_ready", payload={"application_id": str(app.id), "job_id": str(job.id)}))
        await db.commit()
    log.info("report done session=%s scored=%d unscored=%d fallback=%s", session_id, len(evals), unscored, narrative_fallback)


async def mark_report_failed(sm: async_sessionmaker, session_id: uuid.UUID) -> None:
    async with sm() as db:
        report = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == session_id))).scalar_one_or_none()
        if report is not None and report.status != ReportStatus.DONE:
            report.status = ReportStatus.FAILED
            await db.commit()



async def mark_report_queued(sm: async_sessionmaker, session_id: uuid.UUID) -> None:
    """재시도 대기 중에는 리포트도 queued 로 되돌려 '생성 중' 으로 오해하지 않게 한다."""
    async with sm() as db:
        report = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == session_id))).scalar_one_or_none()
        if report is not None and report.status == ReportStatus.RUNNING:
            report.status = ReportStatus.QUEUED
            await db.commit()
