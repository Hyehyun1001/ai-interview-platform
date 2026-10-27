"""공고·지원 REST 스키마 (TRD §7.2). 지원자 응답에는 평가 가중치·합격선 등 내부 설정을 포함하지 않는다."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AiPassPrediction, ApplicationStatus, FinalDecision, ReportStatus


class JobSummary(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str
    job_category: str | None = None
    deadline_at: datetime | None = None
    headcount: int | None = None
    coding_test_enabled: bool
    applicant_applied: bool = False  # 내가 이미 지원했는가


class JobList(BaseModel):
    items: list[JobSummary]
    page: int
    limit: int
    total: int


class JobDetail(JobSummary):
    duties: str | None = None
    requirements: str | None = None
    preferred: str | None = None
    answer_time_limit_sec: int | None = None
    application_id: uuid.UUID | None = None


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent: bool
    consent_version: str = Field(min_length=1, max_length=20)


class ApplyResponse(BaseModel):
    application_id: uuid.UUID


class MyJobRef(BaseModel):
    id: uuid.UUID
    title: str
    deadline_at: datetime | None = None


class MyApplication(BaseModel):
    application_id: uuid.UUID
    job: MyJobRef
    status: ApplicationStatus
    session_id: uuid.UUID | None = None
    report_status: ReportStatus | None = None
    result: FinalDecision | None = None  # 안내 메일 발송(result_notified_at) 이후에만
    applied_at: datetime


__all__ = ["JobSummary", "JobList", "JobDetail", "ApplyRequest", "ApplyResponse", "MyApplication", "MyJobRef", "AiPassPrediction"]
