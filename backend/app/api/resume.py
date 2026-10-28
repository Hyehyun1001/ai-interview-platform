"""이력서 REST (TRD §7.3). PDF 추출은 백그라운드로 처리하고 결과는 GET /resume-jobs/{id} 로 polling 한다."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.extractor import extract_resume
from app.ai.rag.pdf_parser import PdfError, parse_pdf_isolated, split_sections, validate_pdf_upload
from app.core.config import Settings
from app.core.deps import get_current_user, get_db, get_settings_dep, require_role
from app.core.errors import ApiError
from app.core.services import Services
from app.models import Application, JobPosting, Resume, ResumeSnapshot, User
from app.models.base import utcnow
from app.models.enums import ApplicationStatus, ResumeSource, UserRole
from app.schemas.resume import ResumeSchema, is_basic_info_complete
from app.schemas.resume_api import ApplicationResumeIn, ResumeJobOut, ResumeOut, ResumeSnapshotOut, ResumeUploadAccepted

router = APIRouter(tags=["resume"])
RESUME_JOB_TTL_S = 1800
MAX_RESUME_JOBS_PER_USER = 3


def _services(request: Request) -> Services:
    return request.app.state.services


async def _upsert_resume(db: AsyncSession, user_id: uuid.UUID, source: ResumeSource, data: ResumeSchema, file_path: str | None = None) -> Resume:
    row = (await db.execute(select(Resume).where(Resume.user_id == user_id))).scalar_one_or_none()
    payload = data.model_dump()
    complete = is_basic_info_complete(data)
    if row is None:
        row = Resume(user_id=user_id, source=source, data=payload, file_path=file_path, basic_info_complete=complete)
        db.add(row)
    else:
        row.source, row.data, row.basic_info_complete = source, payload, complete
        if file_path:
            row.file_path = file_path
    await db.commit()
    return row


@router.get("/me/resume", response_model=ResumeOut)
async def get_my_resume(user: User = Depends(require_role(UserRole.APPLICANT)), db: AsyncSession = Depends(get_db)) -> ResumeOut:
    row = (await db.execute(select(Resume).where(Resume.user_id == user.id))).scalar_one_or_none()
    if row is None:
        raise ApiError(404, "RESUME_NOT_FOUND", "등록된 이력서가 없습니다")
    return ResumeOut(source=row.source, data=ResumeSchema.model_validate(row.data) if row.data else None,
                     basic_info_complete=row.basic_info_complete, updated_at=row.updated_at)


@router.put("/me/resume", response_model=ResumeOut)
async def put_my_resume(body: ResumeSchema, user: User = Depends(require_role(UserRole.APPLICANT)), db: AsyncSession = Depends(get_db)) -> ResumeOut:
    """직접 작성·수정. 기본 정보가 부족해도 저장은 허용한다(지원 확정 시점에 검증) — 작성 중 임시 저장."""
    row = await _upsert_resume(db, user.id, ResumeSource.MANUAL, body)
    return ResumeOut(source=row.source, data=body, basic_info_complete=row.basic_info_complete, updated_at=row.updated_at)


@router.post("/me/resume-popup/dismiss", status_code=204)
async def dismiss_popup(user: User = Depends(require_role(UserRole.APPLICANT)), db: AsyncSession = Depends(get_db)) -> Response:
    user = await db.merge(user)
    user.resume_popup_dismissed_at = utcnow()
    await db.commit()
    return Response(status_code=204)


# ── PDF 업로드 (비동기) ──────────────────────────────────────────────────────────
async def _process_pdf(svc: Services, settings: Settings, job_id: str, user_id: uuid.UUID, data: bytes, path: Path, sm) -> None:  # noqa: ANN001
    job = svc.resume_jobs[job_id]
    try:
        parsed = await run_in_threadpool(parse_pdf_isolated, data)
        path.unlink(missing_ok=True)  # 완료 상태가 보이기 전에 지운다
        sections = split_sections(parsed.text)
        result = await extract_resume(svc.extract_llm_factory or svc.llm_factory, sections, timeout_s=settings.resume_extract_timeout_s)
        job.update(status="done", data=result.resume.model_dump(), used_ocr=parsed.used_ocr, dropped=result.dropped, fell_back=result.fell_back)
        # 추출 결과는 마이페이지 등록본에 쓰지 않는다 (PRD §10 #11). 지원자가 제출 단계에서 "마이페이지에도 저장"을 고르면 PUT /me/resume 이 호출된다.
    except PdfError as e:
        job.update(status="failed", error_code=e.code, error_message=e.message)
    except Exception as e:  # noqa: BLE001  원문·PII 는 기록하지 않는다
        job.update(status="failed", error_code="EXTRACT_FAILED", error_message="이력서를 분석하지 못했습니다. 직접 작성해 주세요.")
        _ = e
    finally:
        path.unlink(missing_ok=True)  # 어떤 등록본·스냅샷도 원본 PDF 를 참조하지 않는다 — 개인정보 원본을 남기지 않는다


@router.post("/me/resume/upload", response_model=ResumeUploadAccepted, status_code=202)
async def upload_resume(file: UploadFile, request: Request, user: User = Depends(require_role(UserRole.APPLICANT)),
                        settings: Settings = Depends(get_settings_dep)) -> ResumeUploadAccepted:
    svc = _services(request)
    now = asyncio.get_event_loop().time()
    for k in [k for k, v in svc.resume_jobs.items() if now - v["_created"] > RESUME_JOB_TTL_S]:
        svc.resume_jobs.pop(k, None)
    if sum(1 for v in svc.resume_jobs.values() if v["_user"] == user.id and v["status"] == "running") >= MAX_RESUME_JOBS_PER_USER:
        raise ApiError(429, "RATE_LIMITED", "처리 중인 업로드가 있습니다. 잠시 후 다시 시도해 주세요")
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        await run_in_threadpool(validate_pdf_upload, file.filename or "", file.content_type, data)
    except PdfError as e:
        raise ApiError(e.http_status, e.code, e.message) from e
    folder = settings.media_root / "resumes"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / f"{uuid.uuid4()}.pdf"  # 원본 파일명은 저장하지 않는다
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    job_id = uuid.uuid4().hex
    svc.resume_jobs[job_id] = {"status": "running", "_user": user.id, "_created": now}
    svc.spawn(_process_pdf(svc, settings, job_id, user.id, data, path, request.app.state.sessionmaker), f"resume:{job_id}")
    return ResumeUploadAccepted(job_id=job_id)


@router.get("/resume-jobs/{job_id}", response_model=ResumeJobOut)
async def get_resume_job(job_id: str, request: Request, user: User = Depends(require_role(UserRole.APPLICANT))) -> ResumeJobOut:
    job = _services(request).resume_jobs.get(job_id)
    if job is None or job["_user"] != user.id:  # 남의 작업 존재 여부를 숨긴다
        raise ApiError(404, "NOT_FOUND", "작업을 찾을 수 없습니다")
    return ResumeJobOut(**{k: v for k, v in job.items() if not k.startswith("_")})


# ── 지원용 이력서 확정 (스냅샷) ──────────────────────────────────────────────────
async def _owned_application(db: AsyncSession, application_id: uuid.UUID, user: User) -> Application:
    app = (await db.execute(select(Application).where(Application.id == application_id, Application.user_id == user.id))).scalar_one_or_none()
    if app is None:
        raise ApiError(404, "NOT_FOUND", "지원 내역을 찾을 수 없습니다")
    return app


@router.put("/applications/{application_id}/resume", response_model=ResumeSnapshotOut)
async def confirm_application_resume(application_id: uuid.UUID, body: ApplicationResumeIn, user: User = Depends(require_role(UserRole.APPLICANT)),
                                     db: AsyncSession = Depends(get_db)) -> ResumeSnapshotOut:
    app = await _owned_application(db, application_id, user)
    from app.models import InterviewSession  # 순환 import 방지

    if (await db.execute(select(InterviewSession.id).where(InterviewSession.application_id == app.id))).first():
        raise ApiError(409, "SESSION_ALREADY_CREATED", "면접이 준비된 뒤에는 이력서를 바꿀 수 없습니다")
    resume_row = (await db.execute(select(Resume).where(Resume.user_id == user.id))).scalar_one_or_none()
    if body.source == "mypage":
        if resume_row is None or not resume_row.data:
            raise ApiError(404, "RESUME_NOT_FOUND", "마이페이지에 등록된 이력서가 없습니다")
        data = ResumeSchema.model_validate(resume_row.data)
    else:
        if body.data is None:
            raise ApiError(422, "VALIDATION_ERROR", "이력서 내용이 필요합니다", {"fields": [{"field": "data", "message": "필수 항목입니다"}]})
        data = body.data
    if not is_basic_info_complete(data):
        raise ApiError(422, "BASIC_INFO_REQUIRED", "성명과 학력(학교명) 또는 경력(회사명)을 1건 이상 입력해 주세요")
    snap = (await db.execute(select(ResumeSnapshot).where(ResumeSnapshot.application_id == app.id))).scalar_one_or_none()
    payload = data.model_dump()
    if snap is None:
        snap = ResumeSnapshot(application_id=app.id, resume_id=resume_row.id if resume_row else None, data=payload, standard_view=payload)
        db.add(snap)
    else:
        snap.data, snap.standard_view = payload, payload
    if app.status == ApplicationStatus.APPLIED:
        app.status = ApplicationStatus.PREPARED  # 이력서 확정 → 장치 점검 대기
    await db.commit()
    return ResumeSnapshotOut(application_id=app.id, data=data, basic_info_complete=True)


@router.get("/applications/{application_id}/resume/standard", response_model=ResumeSnapshotOut)
async def standard_view(application_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> ResumeSnapshotOut:
    """지원자 본인 또는 해당 공고 회사의 담당자만 (NFR-S6)."""
    q = select(ResumeSnapshot, Application).join(Application, Application.id == ResumeSnapshot.application_id).where(Application.id == application_id)
    row = (await db.execute(q)).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "이력서를 찾을 수 없습니다")
    snap, app = row
    if user.role == UserRole.APPLICANT:
        allowed = app.user_id == user.id
    else:
        company = (await db.execute(select(JobPosting.company_id).where(JobPosting.id == app.job_id))).scalar_one_or_none()
        allowed = company is not None and company == user.company_id
    if not allowed:
        raise ApiError(404, "NOT_FOUND", "이력서를 찾을 수 없습니다")
    return ResumeSnapshotOut(application_id=app.id, data=ResumeSchema.model_validate(snap.standard_view or snap.data), basic_info_complete=True)
