"""지원자 리포트 조회 (TRD §7.4, §7.8.3). 지원자 응답에는 AI 예상 합불·가중치·내부 설정을 절대 포함하지 않는다."""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sessions import owned_session
from app.core.deps import get_db
from app.core.deps import require_role
from app.core.errors import ApiError
from app.models import EvaluationReport, InterviewTurn, ReportScore, User
from app.models.base import utcnow
from app.models.enums import ReportStatus, SessionState, UserRole

router = APIRouter(tags=["reports"])
ETA_TOTAL_SEC = 240  # 목표 3~5분의 중간값. 정확도를 보장하지 않는 추정 (TRD §7.8.3)


class Quote(BaseModel):
    ref: str
    quote: str


class FeedbackItem(BaseModel):
    rank: int
    title: str
    detail: str
    evidence: list[Quote]  # 비어 있을 수 있다(점수 기반 대체 문구) — UI 는 근거가 있는 경우에만 [근거] 를 보여 준다


class CriterionScoreOut(BaseModel):
    criterion: str
    score: float


class TurnScore(BaseModel):
    criterion: str
    score: float
    comment: str | None
    evidence: list[Quote]


class TurnFeedback(BaseModel):
    turn_no: int
    kind: str
    question: str
    answer_text: str | None  # 보관 기간 경과 등으로 삭제되면 null
    scores: list[TurnScore]  # 비어 있으면 "평가 정보 없음"


class ReportBody(BaseModel):
    total_score: float
    summary: str
    criteria: list[CriterionScoreOut]
    strengths: list[FeedbackItem]
    improvements: list[FeedbackItem]
    turns: list[TurnFeedback]
    gaze_away_ratio: float | None
    degraded_mode: bool


class ReportResponse(BaseModel):
    """`done` → 200 + report, `failed` → 200, `queued|running` → 202 + stage/progress/eta_sec."""

    status: Literal["queued", "running", "done", "failed"]
    stage: Literal["transcript", "scoring", "summary"] | None = None
    progress: float | None = None
    eta_sec: int | None = None
    report: ReportBody | None = None


def _quotes(raw: list | None) -> list[Quote]:
    return [Quote(ref=str(e.get("ref", "")), quote=str(e.get("quote", ""))) for e in (raw or []) if isinstance(e, dict) and e.get("quote")]


def _items(raw: list | None) -> list[FeedbackItem]:
    return [FeedbackItem(rank=int(i.get("rank", n + 1)), title=i["title"], detail=i["detail"], evidence=_quotes(i.get("evidence")))
            for n, i in enumerate(raw or [])]


@router.get("/sessions/{session_id}/report", response_model=ReportResponse)
async def get_report(session_id: uuid.UUID, response: Response, user: User = Depends(require_role(UserRole.APPLICANT)),
                     db: AsyncSession = Depends(get_db)) -> ReportResponse:
    sess = await owned_session(db, session_id, user)
    if sess.state not in (SessionState.FINISHED, SessionState.CODING):
        raise ApiError(409, "SESSION_NOT_FINISHED", "면접이 끝난 뒤에 리포트를 볼 수 있습니다", {"state": sess.state.value})
    rep = (await db.execute(select(EvaluationReport).where(EvaluationReport.session_id == session_id))).scalar_one_or_none()
    if rep is None or rep.status in (ReportStatus.QUEUED, ReportStatus.RUNNING):
        response.status_code = 202
        running = rep is not None and rep.status == ReportStatus.RUNNING
        started = rep.updated_at if rep is not None else utcnow()
        elapsed = max(0, int((utcnow() - started).total_seconds()))
        eta = max(0, ETA_TOTAL_SEC - elapsed) if running else ETA_TOTAL_SEC
        return ReportResponse(status="running" if running else "queued", stage="scoring" if running else "transcript",
                              progress=round(min(0.9, elapsed / ETA_TOTAL_SEC), 2) if running else 0.05, eta_sec=eta)
    if rep.status == ReportStatus.FAILED:
        return ReportResponse(status="failed")
    turns = (await db.execute(select(InterviewTurn).where(InterviewTurn.session_id == session_id).order_by(InterviewTurn.turn_no))).scalars().all()
    scores = (await db.execute(select(ReportScore).where(ReportScore.report_id == rep.id))).scalars().all()
    overall = [CriterionScoreOut(criterion=s.criterion.value, score=float(s.score)) for s in scores if s.turn_id is None]
    out_turns = []
    for t in turns:
        ts = [TurnScore(criterion=s.criterion.value, score=float(s.score), comment=s.comment, evidence=_quotes(s.evidence)) for s in scores if s.turn_id == t.id]
        out_turns.append(TurnFeedback(turn_no=t.turn_no, kind=t.kind.value, question=t.question_text, answer_text=t.answer_text, scores=ts))
    body = ReportBody(total_score=round(float(rep.total_score or 0), 1), summary=rep.summary or "", criteria=overall, strengths=_items(rep.strengths),
                      improvements=_items(rep.improvements), turns=out_turns, gaze_away_ratio=rep.gaze_away_ratio, degraded_mode=sess.degraded_mode)
    return ReportResponse(status="done", report=body)
