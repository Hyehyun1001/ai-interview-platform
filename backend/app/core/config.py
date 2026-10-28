"""환경 설정 (TRD §8.2). 필수값(JWT_SECRET, DATA_ENCRYPTION_KEY) 누락·형식 오류 시 기동을 거부한다."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


# 개발 기본값: <저장소>/data/dev.db (data/ 는 gitignore 대상)
DEFAULT_DATABASE_URL = f"sqlite+aiosqlite:///{REPO_ROOT / 'data' / 'dev.db'}"

_ENV = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")


class DatabaseSettings(BaseSettings):
    """DATABASE_URL 만 읽는다. Alembic 이 비밀키(JWT_SECRET 등) 없이도 마이그레이션을 실행할 수 있게 분리."""

    model_config = _ENV

    database_url: str = DEFAULT_DATABASE_URL


class Settings(DatabaseSettings):

    app_env: Literal["dev", "prod"] = "dev"
    allowed_origins: str = "http://localhost:3000"  # 콤마 구분
    max_concurrent_sessions: int = 1
    interview_main_count: int = Field(default=10, ge=1, le=10)  # 메인 질문 수 (TRD §3.4: 기본 10). 개발·E2E 에서 줄일 수 있다

    jwt_secret: str
    jwt_access_ttl_min: int = 15
    jwt_refresh_ttl_days: int = 7
    data_encryption_key: str
    ws_token_ttl_sec: int = 60

    # ── AI 파이프라인 (TRD §8.2) ──
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b-instruct-q4_K_M"
    ollama_keep_alive: str = "30m"
    llm_timeout_s: float = 8.0
    llm_num_ctx: int = 6144  # report_num_ctx 와 같게 둔다: Ollama 는 num_ctx 가 다르면 모델을 다시 로드한다(실측 +약 10초: 로드 2.4~3초 + 입력 재처리 4.8초)
    embed_model: str = "BAAI/bge-m3"
    embed_device: str = "mps"
    embed_keep_resident: Literal["auto", "true", "false"] = "auto"
    chroma_path: Path = REPO_ROOT / "data" / "chroma"
    media_root: Path = REPO_ROOT / "data" / "media"
    # ── 리포트 워커 (TRD §1.3, §3.4 report_chain) ──
    # 이력서 구조화 추출: 출력 JSON(학력·경력·프로젝트·기술·자격)이 길어 면접용 num_predict(256)로는 중간에 잘린다(실측: 프로젝트 3개 중 1개, 기술·자격 0개)
    resume_extract_num_predict: int = Field(default=1536, ge=256, le=4096)
    resume_extract_timeout_s: float = 90.0  # 시도당 상한. 비스트리밍 호출이라 읽기 대기(HTTP)와 전체 대기 모두 이 값을 쓴다
    report_num_ctx: int = 6144        # 면접(llm_num_ctx)과 같은 값을 유지해야 번갈아 쓸 때 모델 재로드가 생기지 않는다
    report_num_predict: int = 900     # 턴 평가 JSON(5항목 코멘트+근거)과 총평 JSON 이 256 토큰에는 들어가지 않는다
    report_llm_timeout_s: float = 150.0
    report_poll_interval_s: float = 3.0
    report_max_attempts: int = 3
    report_worker_embedded: bool = False  # True 면 API 프로세스 안에서 워커 루프를 함께 실행 (개발 편의). 운영은 `python -m app.worker`
    # ── 코딩테스트 샌드박스 (TRD §5, §8.2). 기본 꺼짐: Docker 와 사전 빌드된 sandbox-* 이미지가 필요하다 ──
    sandbox_enabled: bool = False
    sandbox_time_limit_sec: int = Field(default=3, ge=1, le=10)
    sandbox_memory_mb: int = Field(default=128, ge=32, le=512)
    # ── 사내 SMTP (합불 안내 메일, TRD §7.6). 비어 있으면 메일 발송은 503 MAIL_NOT_CONFIGURED ──
    smtp_host: str = ""
    smtp_port: int = 25
    smtp_from: str = "recruit@corp.local"
    smtp_starttls: bool = False
    stt_engine: Literal["faster-whisper", "mlx-whisper"] = "faster-whisper"
    stt_model: str = "large-v3-turbo"
    stt_compute_type: str = "int8"
    stt_cpu_threads: int = 6  # M0 실측 (TRD §4.2)
    tts_provider: Literal["local", "edge"] = "local"
    tts_voice: str = "Yuna"

    @field_validator("jwt_secret")
    @classmethod
    def _jwt_secret_strong(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET 은 32자 이상이어야 합니다")
        return v

    @field_validator("data_encryption_key")
    @classmethod
    def _fernet_key_valid(cls, v: str) -> str:
        try:
            Fernet(v.encode())
        except Exception as e:  # noqa: BLE001
            raise ValueError("DATA_ENCRYPTION_KEY 는 유효한 Fernet 키여야 합니다") from e
        return v

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # 필수값은 환경변수/.env 에서 로드
