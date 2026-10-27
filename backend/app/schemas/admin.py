"""관리자 REST 스키마 (TRD §7.6, §7.8.1, §7.8.5). 프론트 types/admin.ts 는 이 스키마의 OpenAPI 생성 타입으로 대체된다."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AiPassPrediction, FinalDecision, JobStatus, ReportStatus, ScheduleType, TimelineKind, TurnKind

Range = Literal["7d", "30d", "90d"]


class UpcomingInterviews(BaseModel):
    total: int
    today: int
    within_7d: int


class OpenJobs(BaseModel):
    total: int
    coding_on: int


class DashboardSummary(BaseModel):
    upcoming_interviews: UpcomingInterviews
    open_jobs: OpenJobs
    unreviewed_applicants: int
    closing_soon_jobs: int


class JobCategoryStat(BaseModel):
    category: str
    avg_score: float
    pass_rate: float | None  # 확정된 결정이 없으면 null (0% 와 구분)
    applicants: int


class MonthlyCount(BaseModel):
    month: str
    count: int


class DashboardStats(BaseModel):
    by_job_category: list[JobCategoryStat]
    monthly_applicants: list[MonthlyCount]


class RecentJob(BaseModel):
    id: uuid.UUID
    title: str
    status: JobStatus
    deadline_at: datetime | None
    applicant_count: int
    unreviewed_count: int
    coding_test_enabled: bool
    coding_test_time_limit_sec: int | None
    updated_at: datetime


class RecentApplicant(BaseModel):
    application_id: uuid.UUID
    name: str
    job_id: uuid.UUID
    job_title: str
    ai_total_score: float | None
    ai_pass_prediction: AiPassPrediction
    report_status: ReportStatus
    final_decision: FinalDecision
    interview_ended_at: datetime
    reviewed: bool


class DashboardResponse(BaseModel):
    range: Range
    summary: DashboardSummary
    stats: DashboardStats
    recent_jobs: list[RecentJob]
    recent_completed_applicants: list[RecentApplicant]


class ApplicantPage(BaseModel):
    items: list[RecentApplicant]
    page: int
    limit: int
    total: int


class ReportQuote(BaseModel):
    ref: str
    quote: str


class ReportFeedback(BaseModel):
    rank: int
    title: str
    detail: str
    evidence: list[ReportQuote]


class ReportCriterion(BaseModel):
    criterion: str
    score: float
    weight: float | None  # 실제 합산에 쓰인 가중치(%) — 점수 없는 항목을 뺀 재정규화 후 값


class ReportSummary(BaseModel):
    """담당자 전용 평가 요약(UI_SPEC §5.6.1 평가 요약 탭). 지원자용 리포트와 달리 가중치·감점 정보를 포함한다."""

    summary: str | None
    criteria: list[ReportCriterion]
    strengths: list[ReportFeedback]
    improvements: list[ReportFeedback]
    gaze_away_ratio: float | None
    gaze_penalty: float
    scored_turns: int | None
    unscored_turns: int | None


class ApplicationDetail(BaseModel):
    application_id: uuid.UUID
    session_id: uuid.UUID | None = None
    coding_test_enabled: bool = False  # 꺼져 있으면 제출 코드 탭을 숨긴다
    report: ReportSummary | None = None  # 리포트가 done 일 때만
    applicant_name: str
    job_id: uuid.UUID
    job_title: str
    ai_total_score: float | None
    ai_pass_prediction: AiPassPrediction
    report_status: ReportStatus
    final_decision: FinalDecision
    interview_ended_at: datetime | None


# ── 타임라인 ──
class TimelineWord(BaseModel):
    w: str
    s: float
    e: float
    p: float | None = None


class TimelineSegment(BaseModel):
    start_ms: int
    end_ms: int
    kind: TimelineKind
    text: str | None = None
    ai_comment: str | None = None
    severity: int | None = None
    words: list[TimelineWord] | None = None


class GazeEventOut(BaseModel):
    start_ms: int
    end_ms: int
    kind: Literal["gaze_away", "face_lost", "multi_face"]


class TurnReviewScore(BaseModel):
    criterion: str
    score: float
    comment: str | None = None


class TurnReview(BaseModel):
    scores: list[TurnReviewScore]


class TimelineTurn(BaseModel):
    turn_id: uuid.UUID
    turn_no: int
    kind: TurnKind
    question: str
    audio_url: str | None  # 음성이 삭제되었거나 없으면 null
    duration_ms: int
    segments: list[TimelineSegment]
    gaze_events: list[GazeEventOut]
    answer_text: str | None = None
    review: TurnReview | None = None


class TimelineResponse(BaseModel):
    application_id: uuid.UUID
    turns: list[TimelineTurn]


# ── 일정 · 알림 · 시스템 ──
class ScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    type: ScheduleType
    job_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    starts_at: datetime
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def _tz_and_range(self) -> ScheduleCreate:
        for f in ("starts_at", "ends_at"):
            v = getattr(self, f)
            if v is not None and v.tzinfo is None:
                raise ValueError(f"{f} 는 시간대 정보를 포함해야 합니다")
        if self.ends_at is not None and self.ends_at < self.starts_at:
            raise ValueError("종료 시각은 시작 시각 이후여야 합니다")
        return self


class ScheduleOut(BaseModel):
    id: uuid.UUID
    title: str
    type: ScheduleType
    job_id: uuid.UUID | None
    application_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime | None


class JobHistoryItem(BaseModel):
    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    action: str
    actor_name: str | None  # 계정이 삭제되었거나 시스템 동작이면 null
    created_at: datetime


class JobHistoryPage(BaseModel):
    items: list[JobHistoryItem]
    page: int
    limit: int
    total: int


class ScheduleCreated(BaseModel):
    id: uuid.UUID


class NotificationItem(BaseModel):
    id: uuid.UUID
    type: str
    payload: dict | None
    read_at: datetime | None
    created_at: datetime


class NotificationsResponse(BaseModel):
    items: list[NotificationItem]
    unread_count: int


class ExternalTransfer(BaseModel):
    enabled: bool
    tts_edge: bool
    cloud_fallback: bool
    count: int


class ModelState(BaseModel):
    name: str
    loaded: bool | None  # 알 수 없으면 null


class SystemModels(BaseModel):
    llm: ModelState
    stt: ModelState
    tts: ModelState
    embed: ModelState


class SystemMetrics(BaseModel):
    pressure: Literal["normal", "warn", "critical"]
    free_gb: float
    models: SystemModels
    external_transfer: ExternalTransfer
    sandbox_enabled: bool = False  # 코딩테스트 샌드박스 사용 가능 여부 (꺼져 있으면 공고에서 코딩테스트를 켤 수 없다)
