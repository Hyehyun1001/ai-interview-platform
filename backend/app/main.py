"""FastAPI 앱 팩토리. 실행: cd backend && uvicorn app.main:app --reload  (환경변수/.env 필요, .env.example 참고)"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, admin_jobs, admin_review, auth, coding, jobs, media, reports, resume, sessions, ws
from app.core.config import Settings, get_settings
from app.core.crypto import init_crypto
from app.core.database import create_db
from app.core.errors import install_error_handlers, install_openapi
from app.core.rate_limit import SlidingWindowLimiter
from app.core.services import Services, build_default_services
from app.core.ws_tokens import WsTokenRegistry
from app.interview.engines import build_default_engines
from app.interview.manager import SessionManager
from app.interview.runtime import Engines

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, engines: Engines | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    init_crypto(settings.data_encryption_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN202
        engine, sessionmaker = create_db(settings.database_url)
        app.state.engine, app.state.sessionmaker = engine, sessionmaker
        app.state.session_manager = SessionManager(sessionmaker, engines or build_default_engines(settings, sessionmaker),
                                                   settings.max_concurrent_sessions)
        stop, worker_task = asyncio.Event(), None
        if settings.report_worker_embedded:  # 개발 편의: API 프로세스 안에서 워커 루프 실행. 운영은 `python -m app.worker`
            from app.ai.guardrail import DbGuardrailEventSink
            from app.ai.llm import report_llm_factory
            from app.worker.runner import ReportWorker

            worker = ReportWorker(sessionmaker, app.state.services.report_llm_factory or report_llm_factory(settings), sink=DbGuardrailEventSink(sessionmaker),
                                  poll_interval_s=settings.report_poll_interval_s, max_attempts=settings.report_max_attempts,
                                  llm_timeout_s=settings.report_llm_timeout_s, model_name=settings.ollama_model)
            worker_task = asyncio.create_task(worker.run_forever(stop), name="report-worker")
        yield
        stop.set()
        if worker_task is not None:
            try:
                await asyncio.wait_for(worker_task, timeout=5)
            except asyncio.TimeoutError:  # 처리 중이던 잡은 running 으로 남고 requeue_stale 이 되살린다
                worker_task.cancel()
        await app.state.services.aclose()
        await app.state.session_manager.shutdown()
        await engine.dispose()

    app = FastAPI(
        title="AI Interview Platform API", version="0.1.0", lifespan=lifespan,
        docs_url=None if settings.is_prod else "/docs", redoc_url=None,
    )
    app.state.settings = settings
    app.state.services = services or build_default_services(settings)
    app.state.login_limiter = SlidingWindowLimiter(max_events=5, window_sec=60)  # 로그인 5회/분 (TRD §8.3)
    app.state.ws_registry = WsTokenRegistry()  # WS 단기 토큰 1회용 폐기 (TRD §4.1)

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.origins, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next: Any):  # noqa: ANN202
        rid = uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-Id"] = rid
        return response

    install_error_handlers(app)
    for r in (auth.router, jobs.router, resume.router, sessions.router, reports.router, admin.router, admin_jobs.router, admin_review.router, media.router, coding.router):
        app.include_router(r, prefix=API_PREFIX)
    install_openapi(app)
    app.include_router(ws.router)  # WS 경로는 /api/v1 접두사 없이 /ws/... (TRD §4.1)
    return app


def __getattr__(name: str) -> Any:  # uvicorn app.main:app — import 시점이 아닌 접근 시점에 생성 (테스트에서 환경변수 없이 import 가능)
    if name == "app":
        global _app
        try:
            return _app
        except NameError:
            _app = create_app()
            return _app
    raise AttributeError(name)
