"""공고 작성 마법사 REST 스키마 (TRD §7.6, UI_SPEC ADM-03)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import JobStatus, QuestionBankStatus


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JobWrite(_Strict):
    """부분 수정 허용(보낸 필드만 반영). 생성 시에는 title 만 필수 — 임시 저장은 제목만 있으면 된다."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    job_category: str | None = Field(default=None, max_length=50)
    industry: str | None = Field(default=None, max_length=50)
    headcount: int | None = Field(default=None, ge=1, le=10_000)
    deadline_at: datetime | None = None
    duties: str | None = Field(default=None, max_length=5000)
    requirements: str | None = Field(default=None, max_length=5000)
    preferred: str | None = Field(default=None, max_length=5000)
    contact_email: str | None = Field(default=None, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    work_location: str | None = Field(default=None, max_length=200)
    employment_type: Literal["regular", "contract", "intern", "parttime"] | None = None
    salary_text: str | None = Field(default=None, max_length=100)
    benefits: str | None = Field(default=None, max_length=3000)
    notice: str | None = Field(default=None, max_length=3000)
    answer_time_limit_sec: int | None = Field(default=None, ge=30, le=600)
    coding_test_enabled: bool | None = None
    coding_test_time_limit_sec: int | None = Field(default=None, ge=300, le=14_400)
    updated_at: datetime | None = None  # 동시 편집 감지: 읽은 시점의 값을 돌려보내면 불일치 시 409 STALE_UPDATE


class QuestionIn(_Strict):
    text: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=50)
    time_limit_sec: int | None = Field(default=None, ge=30, le=600)


class QuestionsPut(_Strict):
    items: list[QuestionIn] = Field(max_length=10)


class QuestionOut(BaseModel):
    id: uuid.UUID
    order_no: int | None
    text: str
    category: str | None
    time_limit_sec: int | None


class Weights(_Strict):
    concept_understanding: int = Field(ge=0, le=100)
    logic: int = Field(ge=0, le=100)
    delivery: int = Field(ge=0, le=100)
    attitude: int = Field(ge=0, le=100)
    job_expertise: int = Field(ge=0, le=100)
    code_quality: int = Field(ge=0, le=100)


class WeightsPut(_Strict):
    weights: Weights
    gaze_penalty_enabled: bool = False
    cutoff_score: float | None = Field(default=None, ge=0, le=100)
    cutoff_margin: float = Field(default=5, ge=0, le=20)


class WeightsOut(BaseModel):
    weights: Weights
    gaze_penalty_enabled: bool
    cutoff_score: float | None
    cutoff_margin: float


class FollowupRulesPut(_Strict):
    max_followups: int = Field(ge=1, le=4)
    trigger_ambiguous: bool = True
    trigger_contradiction: bool = True
    trigger_stt_unclear: bool = True
    guardrail_strict: bool = True


class JobOut(BaseModel):
    id: uuid.UUID
    status: JobStatus
    title: str
    job_category: str | None
    industry: str | None
    headcount: int | None
    deadline_at: datetime | None
    duties: str | None
    requirements: str | None
    preferred: str | None
    contact_email: str | None
    work_location: str | None
    employment_type: str | None
    salary_text: str | None
    benefits: str | None
    notice: str | None
    answer_time_limit_sec: int | None
    coding_test_enabled: bool
    coding_test_time_limit_sec: int | None
    updated_at: datetime
    weights: WeightsOut
    followup_rules: FollowupRulesPut
    questions: list[QuestionOut]  # 직접 등록한 질문(order_no 순)
    question_bank_status: QuestionBankStatus
    bank_count: int
    applicant_count: int


class JobListItem(BaseModel):
    id: uuid.UUID
    title: str
    status: JobStatus
    job_category: str | None
    deadline_at: datetime | None
    applicant_count: int
    unreviewed_count: int
    view_count: int = 0
    coding_test_enabled: bool
    updated_at: datetime


class JobListOut(BaseModel):
    items: list[JobListItem]
    page: int
    limit: int
    total: int


class BankOut(BaseModel):
    status: Literal["none", "queued", "running", "done", "failed"]
    items: list[QuestionOut]
    message: str | None = None  # failed 시 사용자 안내 (LLM 불가/JD 부족)


class TemplateCreate(_Strict):
    job_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    title: str
    job_category: str | None
    question_count: int
    coding_test_enabled: bool
    created_at: datetime
