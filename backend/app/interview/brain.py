"""면접 두뇌: 다음 메인 질문과 꼬리질문 결정 (TRD §3.4, §2.3, 흐름도 AI_Interview_Loop).

* 메인 질문: 담당자가 등록한 질문(order_no)을 우선 사용 → 비어 있으면 사전 검색 컨텍스트(precomputed_context)로 생성
  → Guardrail 3회 실패 시 질문 뱅크의 미사용 후보 → 그것도 없으면 JD 기반 일반 질문 (환각 차단, TRD §3.3).
* 꼬리질문: 스트리밍 체인으로 `question` 필드가 닫히는 즉시 TTS 를 시작한다 (TRD §2.4). 실패 시 *생략*.
"""
from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.runnables import Runnable
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.chains.followup_chain import generate_followup, generate_followup_streaming
from app.ai.chains.prompts import FollowupInputs, MainQuestionInputs
from app.ai.chains.question_chain import generate_main_question
from app.ai.errors import LLMUnavailable
from app.ai.guardrail import GroundingContext, GuardrailEventSink
from app.models import Application, FollowupRule, InterviewSession, JobPosting, JobQuestion, ResumeSnapshot
from app.models.enums import QuestionSource
from app.schemas.ai import Evidence, FollowupDecision, MainQuestion

DEFAULT_MAIN_COUNT = 10
DEFAULT_ANSWER_LIMIT_SEC = 120
GENERIC_QUESTIONS = (
    "{job} 직무에서 가장 자신 있는 경험을 구체적으로 말씀해 주세요.",
    "{job} 직무를 수행하며 겪었던 가장 어려운 문제와 해결 과정을 말씀해 주세요.",
    "팀에서 의견이 달랐을 때 어떻게 조율했는지 {job} 직무 경험을 바탕으로 말씀해 주세요.",
    "{job} 직무에서 앞으로 가장 키우고 싶은 역량과 그 이유를 말씀해 주세요.",
)


@dataclass
class QuestionDraft:
    text: str
    category: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    time_limit_sec: int | None = None
    source: str = "generated"  # manual | generated | bank | generic (감사·KPI 용)
    degraded: bool = False  # LLM 연결 실패로 LLM 없이 대체된 질문


@dataclass
class FollowupContext:
    """꼬리질문 판단에 필요한 이번 턴의 정보."""

    session_id: uuid.UUID
    turn_id: uuid.UUID
    question: str
    answer: str
    stt_unclear: bool
    asked: list[str]
    used: int  # 이번 메인 질문에서 이미 한 꼬리질문 수
    max_followups: int


@dataclass
class CodeContext:
    """코딩테스트 제출 직후 코드 꼬리질문의 근거 (TRD §5.6). history: (코드 꼬리질문, 지원자 답변) 누적."""

    submission_id: uuid.UUID
    problem_title: str
    problem_statement: str
    language: str
    source: str
    verdict: str
    case_verdicts: list[str]
    analysis: dict[str, Any] | None = None
    history: list[tuple[str, str]] = field(default_factory=list)

    def as_text(self) -> str:
        passed = sum(1 for v in self.case_verdicts if v == "AC")
        lines = [f"[문제] {self.problem_title}: {self.problem_statement}", f"[언어] {self.language}",
                 f"[채점 결과] {self.verdict} (통과 {passed}/{len(self.case_verdicts)})"]
        if self.analysis:
            a = self.analysis
            lines.append(f"[정적 분석] 린트 {a.get('lint_issues', 0)}건, 최대 복잡도 {a.get('max_complexity', '-')}, 최장 함수 {a.get('max_function_len', '-')}줄")
        lines.append("[제출 코드]\n" + self.source[:3000])
        for q, a_ in self.history:
            lines.append(f"[이전 꼬리질문] {q}\n[지원자 답변] {a_}")
        return "\n".join(lines)


@dataclass
class SessionConfig:
    """세션 시작 시 DB 에서 한 번 읽어 두는 설정 (면접 중 반복 조회 방지)."""

    total_main: int
    answer_limit_sec: int
    max_followups: int
    triggers: dict[str, bool]
    coding_enabled: bool
    coding_limit_sec: int | None
    guardrail_strict: bool


class InterviewBrain(Protocol):
    async def load_config(self, session_id: uuid.UUID) -> SessionConfig: ...
    async def next_main_question(self, session_id: uuid.UUID, index: int, asked: list[str]) -> QuestionDraft: ...
    async def decide_code_followup(self, ctx: CodeContext, asked: list[str], used: int, max_followups: int, session_id: uuid.UUID) -> FollowupDecision: ...
    async def decide_followup(self, ctx: FollowupContext, on_question_ready: Callable[[FollowupDecision], Awaitable[None]]) -> tuple[
        FollowupDecision, bool]:
        """(최종 결정, 음성이 JSON 완성 전에 시작되었는가). 연결 실패는 LLMUnavailable 로 올린다."""
        ...


class ChainBrain:
    """LangChain 체인 + Guardrail 기반 기본 구현. DB 는 읽기 전용으로만 사용한다."""

    def __init__(self, sessionmaker: async_sessionmaker, llm_factory: Callable[[float], Runnable], *,
                 sink: GuardrailEventSink | None = None, timeout_s: float = 8.0, coding_allowed: bool = True):
        self.sm, self.llm_factory, self.sink, self.timeout_s = sessionmaker, llm_factory, sink, timeout_s
        self.coding_allowed = coding_allowed  # SANDBOX_ENABLED=false 면 공고에 코테가 켜져 있어도 면접을 코딩 단계로 보내지 않는다

    async def _load(self, session_id: uuid.UUID) -> tuple[InterviewSession, Application, JobPosting]:
        async with self.sm() as db:
            sess = await db.get(InterviewSession, session_id)
            app = await db.get(Application, sess.application_id)
            job = await db.get(JobPosting, app.job_id)
            return sess, app, job

    async def load_config(self, session_id: uuid.UUID) -> SessionConfig:
        sess, _app, job = await self._load(session_id)
        async with self.sm() as db:
            rules = (await db.execute(select(FollowupRule).where(FollowupRule.job_id == job.id))).scalar_one_or_none()
        slots = (sess.precomputed_context or {}).get("slots") or []
        return SessionConfig(
            total_main=len(slots) or DEFAULT_MAIN_COUNT,
            answer_limit_sec=job.answer_time_limit_sec or DEFAULT_ANSWER_LIMIT_SEC,
            max_followups=rules.max_followups if rules else 2,
            triggers={"trigger_ambiguous": rules.trigger_ambiguous if rules else True,
                      "trigger_contradiction": rules.trigger_contradiction if rules else True,
                      "trigger_stt_unclear": rules.trigger_stt_unclear if rules else True},
            coding_enabled=job.coding_test_enabled and self.coding_allowed, coding_limit_sec=job.coding_test_time_limit_sec,
            guardrail_strict=rules.guardrail_strict if rules else True)

    # ── 메인 질문 ──
    async def next_main_question(self, session_id: uuid.UUID, index: int, asked: list[str]) -> QuestionDraft:
        sess, _app, job = await self._load(session_id)
        async with self.sm() as db:
            qs = (await db.execute(select(JobQuestion).where(JobQuestion.job_id == job.id))).scalars().all()
        manual = {q.order_no: q for q in qs if q.order_no is not None}
        if (q := manual.get(index + 1)) is not None:  # 담당자가 직접 등록한 질문은 그대로 사용
            return QuestionDraft(q.text, q.category, [], q.time_limit_sec, "manual")

        slots = (sess.precomputed_context or {}).get("slots") or []
        slot = slots[index] if index < len(slots) else {}
        resume_hits, jd_hits = slot.get("resume", []), slot.get("jd", [])
        sources = {h["chunk_id"]: h["text"] for h in resume_hits + jd_hits}
        jd_ctx = "\n".join(h["text"] for h in jd_hits) or "\n".join(filter(None, [job.duties, job.requirements]))
        resume_ctx = "\n".join(f"{h['chunk_id']}: {h['text']}" for h in resume_hits)  # 비면 JD 기반 일반 질문 (이력서 언급 금지)
        bank = [q for q in qs if q.source == QuestionSource.AI_BANK and q.order_no is None and q.text not in asked]

        def fallback() -> MainQuestion:  # 질문 뱅크의 미사용 후보 → JD 기반 일반 질문
            if bank:
                return MainQuestion(question=bank[0].text, category=bank[0].category or "직무 역량", evidence=[])
            # 일반 질문도 이미 한 질문과 겹치지 않게 고른다 (실제 E2E 에서 같은 일반 질문이 두 번 나온 문제)
            for tpl in GENERIC_QUESTIONS:
                text = tpl.format(job=job.title)
                if text not in asked:
                    return MainQuestion(question=text, category="직무 역량", evidence=[])
            return MainQuestion(question=f"{job.title} 직무와 관련해 아직 말씀하지 않은 경험이 있다면 소개해 주세요.", category="직무 역량", evidence=[])

        fallback_source = "bank" if bank else "generic"
        try:
            res = await generate_main_question(
                self.llm_factory, MainQuestionInputs(jd_ctx, resume_ctx, "직무 역량", asked),
                GroundingContext(asked_questions=asked, sources=sources), fallback=fallback, sink=self.sink,
                timeout_s=self.timeout_s, session_id=session_id)
        except LLMUnavailable:  # LLM 이 없어도 면접은 계속된다: 질문 뱅크/일반 질문으로 대체 (NFR-R5 경량 모드)
            q = fallback()
            return QuestionDraft(q.question, q.category, [], None, fallback_source, degraded=True)
        q = res.value
        return QuestionDraft(q.question, q.category, q.evidence, None, fallback_source if res.fell_back else "generated")

    # ── 꼬리질문 ──
    async def decide_code_followup(self, ctx: CodeContext, asked: list[str], used: int, max_followups: int, session_id: uuid.UUID) -> FollowupDecision:
        """제출 코드·채점·정적 분석을 근거로 한 텍스트 꼬리질문. 동일한 Guardrail(G2~G6)을 거치고, 3회 실패하면 생략한다."""
        cfg = await self.load_config(session_id)
        text = ctx.as_text()
        gctx = GroundingContext(answer_text=text, resume_text="", asked_questions=asked, sources={"code": text})
        inputs = FollowupInputs("제출한 코드를 설명해 주세요.", text, "code", "(코딩테스트 — 이력서 대신 제출 코드와 채점 결과를 근거로 한다)", {}, asked, used,
                                max_followups, cfg.triggers, False)
        res = await generate_followup(self.llm_factory, inputs, gctx, sink=self.sink, timeout_s=self.timeout_s, session_id=session_id)
        return res.value

    async def decide_followup(self, ctx: FollowupContext, on_question_ready: Callable[[FollowupDecision], Awaitable[None]]) -> tuple[
            FollowupDecision, bool]:
        async with self.sm() as db:
            sess = await db.get(InterviewSession, ctx.session_id)
            app = await db.get(Application, sess.application_id)
            snap = (await db.execute(select(ResumeSnapshot).where(ResumeSnapshot.application_id == app.id))).scalar_one_or_none()
        resume_json = _resume_text(snap)
        answer_ref = f"turn:{ctx.turn_id}"
        gctx = GroundingContext(answer_text=ctx.answer, resume_text=resume_json, asked_questions=ctx.asked,
                                sources={answer_ref: ctx.answer, "resume": resume_json})
        cfg = await self.load_config(ctx.session_id)
        inputs = FollowupInputs(ctx.question, ctx.answer, answer_ref, resume_json, {}, ctx.asked, ctx.used, ctx.max_followups,
                                cfg.triggers, ctx.stt_unclear)
        res = await generate_followup_streaming(
            self.llm_factory, inputs, gctx, on_question_ready=on_question_ready, sink=self.sink, timeout_s=self.timeout_s,
            session_id=ctx.session_id, turn_id=ctx.turn_id)
        return res.value.decision, res.value.spoken_early


def _resume_text(snap: ResumeSnapshot | None) -> str:
    """정규화된 이력서 JSON 전체를 프롬프트에 넣는다 — 면접 중에는 임베딩 없이 (≤ 1,500 토큰, TRD §2.3-3)."""
    if snap is None or not snap.data:
        return "(이력서 없음)"
    import json

    d: dict[str, Any] = {k: v for k, v in snap.data.items() if k != "self_intro"}  # 자소서 본문은 길어 제외
    return json.dumps(d, ensure_ascii=False)[:2500]
