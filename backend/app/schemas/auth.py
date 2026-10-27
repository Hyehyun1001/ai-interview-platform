"""인증 요청/응답 스키마 (Pydantic v2). 검증 규칙은 docs/UI_SPEC.md §4.1.1 과 동일하게 유지한다."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import Gender, UserRole

# 사내 도메인(.local 등)도 허용해야 하므로 email-validator(특수 도메인 거부) 대신 형식만 검증한다
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^010-\d{4}-\d{4}$")


def _normalize_email(v: str) -> str:
    v = v.strip().lower()
    if len(v) > 255 or not _EMAIL_RE.match(v):
        raise ValueError("이메일 형식이 올바르지 않습니다")
    return v


EmailAddress = Annotated[str, AfterValidator(_normalize_email)]


class LoginRole(str, Enum):
    """로그인 화면의 역할 탭. recruiter 탭은 recruiter/admin 계정이 사용한다."""

    APPLICANT = "applicant"
    RECRUITER = "recruiter"

    def accepts(self, role: UserRole) -> bool:
        if self is LoginRole.APPLICANT:
            return role is UserRole.APPLICANT
        return role in (UserRole.RECRUITER, UserRole.ADMIN)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=50)
    email: EmailAddress
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(max_length=128)
    birth_date: date  # YYYY/MM/DD 또는 YYYY-MM-DD
    gender: Gender
    phone: str  # 010-0000-0000

    @field_validator("birth_date", mode="before")
    @classmethod
    def _birth_slash(cls, v: Any) -> Any:
        if isinstance(v, str) and re.fullmatch(r"\d{4}/\d{2}/\d{2}", v.strip()):
            return v.strip().replace("/", "-")
        return v

    @field_validator("birth_date")
    @classmethod
    def _birth_range(cls, v: date) -> date:
        if v >= date.today() or v.year < 1900:
            raise ValueError("생년월일이 올바르지 않습니다")
        return v

    @field_validator("phone")
    @classmethod
    def _phone_format(cls, v: str) -> str:
        if not _PHONE_RE.match(v):
            raise ValueError("연락처는 010-0000-0000 형식이어야 합니다")
        return v

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v) and re.search(r"[^A-Za-z0-9]", v)):
            raise ValueError("비밀번호는 영문, 숫자, 특수문자를 모두 포함해야 합니다")
        return v

    @model_validator(mode="after")
    def _passwords_match(self) -> RegisterRequest:
        if self.password != self.password_confirm:
            raise ValueError("비밀번호가 일치하지 않습니다")
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailAddress
    password: str = Field(min_length=1, max_length=128)  # 로그인은 빈 값만 검증 (규칙 노출 방지)
    role: LoginRole = LoginRole.APPLICANT


class UserOut(BaseModel):
    """생년월일·성별·연락처는 응답에 포함하지 않는다 (NFR-Q4, 최소 노출)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    company_id: uuid.UUID | None = None
    resume_popup_dismissed_at: datetime | None = None
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserOut
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # 초
