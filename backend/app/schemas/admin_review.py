"""지원자 비교 · 최종 결정 · 안내 메일 스키마 (TRD §7.6)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AiPassPrediction, FinalDecision


class CompareApplicant(BaseModel):
    application_id: uuid.UUID
    name: str
    ai_total_score: float | None
    ai_pass_prediction: AiPassPrediction
    criteria: dict[str, float]  # 항목 → 0~100 (채점되지 않은 항목은 키 없음)
    gaze_away_ratio: float | None
    strengths: list[str]  # 제목만 (TOP3)
    improvements: list[str]


class CompareResponse(BaseModel):
    job_id: uuid.UUID
    job_title: str
    axes: list[str]  # 모든 지원자에게 점수가 있는 항목 (레이더 축). code_quality 는 모두 있을 때만 포함
    applicants: list[CompareApplicant]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: FinalDecision
    memo: str | None = Field(default=None, max_length=1000)
    acknowledge_notified: bool = False


class DecisionOut(BaseModel):
    final_decision: FinalDecision
    decided_at: datetime | None


class MailIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    template: Literal["pass", "fail", "schedule"]
    schedule_link: str | None = Field(default=None, max_length=500, pattern=r"^https?://\S+$")


class MailOut(BaseModel):
    sent: bool
    template: str
    result_notified_at: datetime | None
