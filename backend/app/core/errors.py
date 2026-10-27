"""에러 포맷 {"error":{"code","message","details"}} (TRD §7 공통) 와 전역 예외 처리기.

보안: 검증 오류 응답에 요청 입력값(input)을 절대 되돌려주지 않는다 (비밀번호·PII 유출 방지).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")

_STATUS_CODES = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 415: "UNSUPPORTED_MEDIA_TYPE", 422: "VALIDATION_ERROR", 429: "RATE_LIMITED",
}


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None,
                 headers: dict[str, str] | None = None):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message
        self.details, self.headers = details or {}, headers


def error_response(status_code: int, code: str, message: str, details: dict | None = None,
                   request: Request | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "details": details or {}}}
    rid = getattr(getattr(request, "state", None), "request_id", None) if request else None
    if rid:
        body["error"]["request_id"] = rid
    return JSONResponse(body, status_code=status_code, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):  # noqa: ANN202
        return error_response(exc.status_code, exc.code, exc.message, exc.details, request, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):  # noqa: ANN202
        fields = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"].removeprefix("Value error, "),
             "type": e["type"]}
            for e in exc.errors()
        ]  # 'input' 은 의도적으로 제외
        return error_response(422, "VALIDATION_ERROR", "입력값이 올바르지 않습니다", {"fields": fields}, request)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):  # noqa: ANN202
        code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        return error_response(exc.status_code, code, str(exc.detail), None, request, getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # noqa: ANN202
        # 예외 메시지에 PII 가 섞일 수 있어 타입과 요청 ID 만 기록한다
        log.error("unhandled %s request_id=%s", type(exc).__name__, getattr(request.state, "request_id", None))
        return error_response(500, "INTERNAL_ERROR", "서버 오류가 발생했습니다", None, request)


# ── OpenAPI: 실제 응답 포맷과 일치시키기 ─────────────────────────────────────────
class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    """모든 4xx/5xx 응답의 본문 (TRD §7 공통). FastAPI 기본 HTTPValidationError 와 다르다."""

    error: ErrorBody


def install_openapi(app: FastAPI) -> None:
    """422 의 기본 스키마(HTTPValidationError)를 실제 런타임 포맷 ErrorEnvelope 로 바꾼다 → 생성되는 프론트 타입이 실제와 일치한다."""

    def custom() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        comps = schema.setdefault("components", {}).setdefault("schemas", {})
        env = ErrorEnvelope.model_json_schema(ref_template="#/components/schemas/{model}")
        for name, sub in env.pop("$defs", {}).items():
            comps[name] = sub
        comps["ErrorEnvelope"] = env
        for name in ("HTTPValidationError", "ValidationError"):
            comps.pop(name, None)
        for path in schema.get("paths", {}).values():
            for op in path.values():
                if not isinstance(op, dict):
                    continue
                resp = op.get("responses", {})
                resp.pop("422", None)
                resp["422"] = {"description": "Validation Error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}}}
                for code in ("400", "401", "403", "404", "409"):
                    if code in resp:
                        resp[code].setdefault("content", {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}})
        app.openapi_schema = schema
        return schema

    app.openapi = custom  # type: ignore[method-assign]
