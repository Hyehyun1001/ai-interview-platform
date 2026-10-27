"""앱 수준 협력 객체(LLM 팩토리·벡터 저장소 등). 테스트와 개발 스택이 가짜로 바꿀 수 있도록 create_app 에서 주입한다."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import Runnable

from app.core.config import Settings

log = logging.getLogger("app.services")


@dataclass
class Services:
    llm_factory: Callable[[float], Runnable]
    # 지연 생성: bge-m3 의존성(sentence-transformers)이 없거나 로드에 실패하면 None → 이력서 검색 없이 JD 기반 질문으로 진행 (TRD §3.3)
    vector_store_factory: Callable[[], Any | None]
    report_llm_factory: Callable[[float], Runnable] | None = None  # 리포트용(긴 컨텍스트). None 이면 report_llm_factory(settings)
    mailer: Any = None  # app.services.mailer.Mailer. None 이면 설정(SMTP_HOST)으로 생성
    resume_jobs: dict[str, dict[str, Any]] = field(default_factory=dict)  # PII 가 든 추출 결과는 평문 jobs.payload 대신 메모리에만 둔다
    warmups: dict[Any, str] = field(default_factory=dict)  # session_id -> warming | done
    _store: Any = None
    _store_tried: bool = False
    _tasks: set[asyncio.Task] = field(default_factory=set)

    def vector_store(self) -> Any | None:
        if not self._store_tried:
            self._store_tried = True
            try:
                self._store = self.vector_store_factory()
            except Exception as e:  # noqa: BLE001
                log.warning("vector store unavailable: %s", type(e).__name__)
        return self._store

    def spawn(self, coro: Coroutine[Any, Any, Any], name: str) -> None:
        """종료 시점까지 참조를 유지하는 백그라운드 태스크 (GC 로 사라지지 않게)."""
        t = asyncio.create_task(coro, name=name)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def aclose(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)


def default_vector_store(settings: Settings) -> Any:
    from app.ai.rag.embedder import BgeM3Embedder
    from app.ai.rag.store import VectorStore, create_chroma_client

    return VectorStore(create_chroma_client(settings.chroma_path), BgeM3Embedder(settings.embed_model, settings.embed_device))


def build_default_services(settings: Settings) -> Services:
    from app.ai.llm import llm_factory, report_llm_factory
    from app.services.mailer import SmtpMailer

    return Services(llm_factory=llm_factory(settings), vector_store_factory=lambda: default_vector_store(settings),
                    report_llm_factory=report_llm_factory(settings), mailer=SmtpMailer(settings))
