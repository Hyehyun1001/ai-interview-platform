"""모든 모델을 import 하여 Base.metadata 에 등록한다 (Alembic autogenerate 가 참조)."""
from app.models.application import Application, RecruiterNote
from app.models.base import Base
from app.models.interview import CodeSubmission, GazeEvent, InterviewSession, InterviewTurn, VoiceTimeline
from app.models.job import EvalWeight, FollowupRule, JobPosting, JobQuestion
from app.models.ops import AuditLog, BackgroundJob, GuardrailEvent, JobHistory, LlmAuditLog, Notification, Schedule
from app.models.report import EvaluationReport, Highlight, ReportScore
from app.models.resume import Resume, ResumeSnapshot
from app.models.user import Company, User

__all__ = [
    "Base", "Company", "User", "JobPosting", "JobQuestion", "EvalWeight", "FollowupRule", "Resume", "ResumeSnapshot",
    "Application", "RecruiterNote", "InterviewSession", "InterviewTurn", "VoiceTimeline", "GazeEvent", "CodeSubmission",
    "EvaluationReport", "ReportScore", "Highlight", "Schedule", "Notification", "JobHistory", "BackgroundJob",
    "GuardrailEvent", "LlmAuditLog", "AuditLog",
]
