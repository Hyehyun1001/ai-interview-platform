"""도메인 Enum (docs/TRD.md §6.2). DB 에는 VARCHAR + CHECK 로 저장하여 SQLite/PostgreSQL 동일 동작."""
from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    APPLICANT = "applicant"
    RECRUITER = "recruiter"
    ADMIN = "admin"


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class JobStatus(str, enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    DELETED = "deleted"


class QuestionSource(str, enum.Enum):
    MANUAL = "manual"
    AI_BANK = "ai_bank"


class QuestionBankStatus(str, enum.Enum):
    NONE = "none"
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class ResumeSource(str, enum.Enum):
    PDF = "pdf"
    MANUAL = "manual"


class VectorStatus(str, enum.Enum):
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class ApplicationStatus(str, enum.Enum):
    """진행 단계 전용. 합불은 FinalDecision 만이 단일 출처 (TRD §6.2)."""

    APPLIED = "applied"
    PREPARED = "prepared"
    INTERVIEWING = "interviewing"
    INTERVIEW_DONE = "interview_done"
    REPORT_READY = "report_ready"


class FinalDecision(str, enum.Enum):
    PENDING = "pending"
    PASS = "pass"
    FAIL = "fail"


class AiPassPrediction(str, enum.Enum):
    LIKELY_PASS = "likely_pass"
    BORDERLINE = "borderline"
    UNLIKELY = "unlikely"
    UNAVAILABLE = "unavailable"


class SessionState(str, enum.Enum):
    CREATED = "created"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    CODING = "coding"
    FINISHED = "finished"
    ABORTED = "aborted"


class TurnKind(str, enum.Enum):
    MAIN = "main"
    FOLLOWUP = "followup"
    CODE_FOLLOWUP = "code_followup"


class FollowupReason(str, enum.Enum):
    AMBIGUOUS = "ambiguous"
    CONTRADICTION = "contradiction"
    STT_UNCLEAR = "stt_unclear"


class AnswerEndReason(str, enum.Enum):
    USER = "user"
    SILENCE = "silence"
    TIMEOUT = "timeout"


class TimelineKind(str, enum.Enum):
    SPEECH = "speech"
    SILENCE = "silence"
    STT_UNCLEAR = "stt_unclear"
    HIGHLIGHT_GOOD = "highlight_good"
    HIGHLIGHT_BAD = "highlight_bad"


class GazeKind(str, enum.Enum):
    GAZE_AWAY = "gaze_away"
    FACE_LOST = "face_lost"
    MULTI_FACE = "multi_face"


class Verdict(str, enum.Enum):
    AC = "AC"
    WA = "WA"
    TLE = "TLE"
    MLE = "MLE"
    RE = "RE"
    CE = "CE"
    OLE = "OLE"


class ReportStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Criterion(str, enum.Enum):
    CONCEPT_UNDERSTANDING = "concept_understanding"
    LOGIC = "logic"
    DELIVERY = "delivery"
    ATTITUDE = "attitude"
    JOB_EXPERTISE = "job_expertise"
    CODE_QUALITY = "code_quality"


class HighlightKind(str, enum.Enum):
    GOOD = "good"
    BAD = "bad"


class ScheduleType(str, enum.Enum):
    INTERVIEW1 = "interview1"
    INTERVIEW2 = "interview2"
    DEADLINE = "deadline"
    DOC_SCREEN = "doc_screen"


class QueueStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
