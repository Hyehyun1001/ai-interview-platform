"""LLM 출력 규격 (TRD §3.5). 필드 순서 = JSON 키 순서이므로 변경 금지.

FollowupDecision 은 grounding_keywords 가 question 보다 앞에 온다 — 스트리밍 TTS 시작 전에 G2 를 검증하기 위함 (TRD §2.4).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


QUOTE_MAX_CHARS = 80


class Evidence(BaseModel):
    source: Literal["resume", "answer", "jd", "code"]

    @field_validator("source", mode="before")
    @classmethod
    def _coerce_source(cls, v: object) -> object:
        """모델이 source 에 "project"·"experience" 같은 임의 값을 쓰는 일이 잦다. 허용 값이 아니면 이력서 근거로 본다 — 실제 근거 여부는 G3 가 인용문으로 검증한다."""
        return v if v in ("resume", "answer", "jd", "code") else "resume"

    ref: str = Field(max_length=100)  # chunk_id 또는 "turn:{turn_id}"
    quote: str = Field(max_length=QUOTE_MAX_CHARS)  # 근거 원문 일부 (≤ 80자)

    @field_validator("quote", mode="before")
    @classmethod
    def _truncate_long_quote(cls, v: object) -> object:
        """모델은 문장을 통째로 인용해 80자를 자주 넘긴다. 인용의 앞부분은 여전히 원문의 부분 문자열이므로 안전하게 잘라낸다
        (G3 가 잘린 인용을 원문과 다시 대조한다). 길이 때문에 근거 전체를 버리는 것보다 낫다."""
        return v.strip()[:QUOTE_MAX_CHARS] if isinstance(v, str) else v


class MainQuestion(BaseModel):
    question: str = Field(min_length=5, max_length=120)
    category: str
    evidence: list[Evidence] = Field(default_factory=list, max_length=3)


class FollowupDecision(BaseModel):
    needed: bool
    reason: Literal["ambiguous", "contradiction", "stt_unclear", "none"]
    grounding_keywords: list[str] = Field(default_factory=list, max_length=5)
    question: str | None = Field(default=None, max_length=120)
    evidence: list[Evidence] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _consistent(self) -> FollowupDecision:
        if self.needed and not (self.question and self.grounding_keywords):
            raise ValueError("needed=true requires question and grounding_keywords")
        if self.needed and self.reason == "none":
            raise ValueError("needed=true requires a reason other than 'none'")
        if not self.needed and self.question:
            raise ValueError("needed=false must not carry a question")
        return self

    @classmethod
    def skip(cls) -> FollowupDecision:
        """안전한 대체 동작: 꼬리질문 생략 (TRD §3.5 — 잘못된 질문보다 무질문이 안전)."""
        return cls(needed=False, reason="none")


# ── 리포트 (TRD §3.4 report_chain, §6.3) ───────────────────────────────────────
class CriterionEval(BaseModel):
    """루브릭 앵커(1~5) 기반 채점. 0~100 점수는 level × 20 으로 서버가 환산한다."""

    level: int = Field(ge=1, le=5)
    comment: str = Field(min_length=2, max_length=120)

    @field_validator("comment", mode="before")
    @classmethod
    def _trim(cls, v: object) -> object:
        return v.strip()[:120] if isinstance(v, str) else v


class TurnHighlight(BaseModel):
    kind: Literal["good", "bad"]
    quote: str = Field(max_length=QUOTE_MAX_CHARS)  # 답변 원문에서 그대로 인용한 구간
    reason: str = Field(min_length=2, max_length=120)

    @field_validator("quote", mode="before")
    @classmethod
    def _cut_quote(cls, v: object) -> object:
        """Evidence.quote 와 같은 이유: 모델이 문장을 통째로 인용하면 앞 80자만 취해 원문 대조(G3)에 맡긴다."""
        return v.strip()[:QUOTE_MAX_CHARS] if isinstance(v, str) else v

    @field_validator("reason", mode="before")
    @classmethod
    def _trim_reason(cls, v: object) -> object:
        return v.strip()[:120] if isinstance(v, str) else v


class TurnEvaluation(BaseModel):
    """질문 1개(턴)에 대한 항목별 채점. code_quality 는 코딩테스트 결과로만 채점하므로 여기에 없다."""

    concept_understanding: CriterionEval
    logic: CriterionEval
    delivery: CriterionEval
    attitude: CriterionEval
    job_expertise: CriterionEval
    evidence: list[Evidence] = Field(min_length=1, max_length=2)
    highlight: TurnHighlight | None = None


class ReportItem(BaseModel):
    title: str = Field(min_length=2, max_length=40)
    detail: str = Field(min_length=2, max_length=200)
    evidence: list[Evidence] = Field(default_factory=list, max_length=3)  # 비어 있으면 검증 단계에서 항목이 제외된다


class ReportNarrative(BaseModel):
    summary: str = Field(min_length=10, max_length=400)
    strengths: list[ReportItem] = Field(min_length=1, max_length=3)
    improvements: list[ReportItem] = Field(min_length=1, max_length=3)


class BankItem(BaseModel):
    question: str = Field(min_length=5, max_length=120)
    category: str = Field(default="직무 역량", max_length=50)


class QuestionBank(BaseModel):
    items: list[BankItem] = Field(min_length=1, max_length=30)
