"""이력서 REST 스키마 (TRD §7.3)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.enums import ResumeSource
from app.schemas.resume import ResumeSchema


class ResumeOut(BaseModel):
    source: ResumeSource
    data: ResumeSchema | None
    basic_info_complete: bool
    updated_at: datetime


class ResumeUploadAccepted(BaseModel):
    job_id: str


class ResumeJobOut(BaseModel):
    status: Literal["running", "done", "failed"]
    data: ResumeSchema | None = None
    used_ocr: bool = False
    dropped: int = 0
    fell_back: bool = False  # True 면 자동 추출 실패 → 지원자가 직접 작성
    error_code: str | None = None
    error_message: str | None = None


class ApplicationResumeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["mypage", "upload", "manual"]
    data: ResumeSchema | None = None  # source=mypage 이면 생략(등록본 사용)


class ResumeSnapshotOut(BaseModel):
    application_id: uuid.UUID
    data: ResumeSchema
    basic_info_complete: bool
