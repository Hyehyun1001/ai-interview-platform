"""이력서 구조화 스키마 (TRD §3.1 ResumeSchema). 추출 불가 필드는 null — 추측 금지."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Education(_Loose):
    school: str | None = None
    major: str | None = None
    degree: str | None = None
    start: str | None = None
    end: str | None = None


class Experience(_Loose):
    company: str | None = None
    role: str | None = None
    start: str | None = None
    end: str | None = None
    summary: str | None = None


class Project(_Loose):
    title: str | None = None
    role: str | None = None
    period: str | None = None
    tech_stack: list[str] = Field(default_factory=list)
    description: str | None = None


class ResumeSchema(_Loose):
    name: str | None = None
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    self_intro: str | None = None  # 자소서 원문


def is_basic_info_complete(data: ResumeSchema | dict[str, Any] | None) -> bool:
    """기본 정보 필수 규칙 (PRD 10장 #9, TRD §6.2 basic_info_complete):
    성명이 있고, 학교명이 있는 학력 또는 회사명이 있는 경력이 1건 이상. 자소서는 필수 아님."""
    if data is None:
        return False
    r = data if isinstance(data, ResumeSchema) else ResumeSchema.model_validate(data)
    if not (r.name and r.name.strip()):
        return False
    return any(e.school and e.school.strip() for e in r.education) or any(x.company and x.company.strip() for x in r.experience)
