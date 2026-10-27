"""코딩테스트 REST 스키마 (TRD §7, UI_SPEC §4.7)."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["python", "java", "javascript"]
VerdictCode = Literal["AC", "WA", "TLE", "MLE", "RE", "CE", "OLE"]


class LanguageOut(BaseModel):
    id: Language
    label: str
    starter: str


class ExampleOut(BaseModel):
    input: str
    output: str


class ProblemOut(BaseModel):
    problem_id: str
    title: str
    statement: str
    input_format: str
    output_format: str
    constraints: list[str]
    examples: list[ExampleOut]
    languages: list[LanguageOut]
    time_limit_sec: int | None  # 코딩테스트 전체 제한시간(공고 설정)
    exec_time_limit_sec: int
    memory_limit_mb: int
    case_count: int
    submitted: bool


class CodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language
    source: str = Field(min_length=1, max_length=50_000)


class CaseOut(BaseModel):
    index: int
    verdict: VerdictCode
    runtime_ms: int
    visible: bool  # 샘플(공개) 케이스만 stdout/stderr 를 담는다
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False


class RunOut(BaseModel):
    verdict: VerdictCode
    cases: list[CaseOut]
    compile_log: str = ""


class SubmitAccepted(BaseModel):
    submission_id: uuid.UUID


class ResultOut(BaseModel):
    status: Literal["none", "judging", "done"]
    submission_id: uuid.UUID | None = None
    language: str | None = None
    verdict: VerdictCode | None = None
    runtime_ms: int | None = None
    cases: list[CaseOut] = []
    compile_log: str = ""
    # 담당자 전용 (지원자 응답에는 항상 None)
    source_code: str | None = None
    static_analysis: dict | None = None
