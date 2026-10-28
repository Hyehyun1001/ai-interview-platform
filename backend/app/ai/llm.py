"""로컬 LLM(Ollama) 어댑터 (TRD §3.4~3.6). 운영 로직에서 외부 SaaS 호출은 없다 (CLAUDE.md: ZERO external calls).

Cloud Fallback(§3.6)은 v2 범위·기본 OFF 이므로 구현하지 않는다. 연결 실패는 `LLMUnavailable` 로 올려 호출자가
경량 모드(꼬리질문 생략 · 질문 뱅크 대체)를 선택한다.
"""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.runnables import Runnable

from app.core.config import Settings

NUM_PREDICT = 256  # TRD §3.5: Ollama format="json", temperature=0.2, num_ctx=4096, num_predict=256


def build_chat_ollama(settings: Settings, temperature: float, *, num_ctx: int | None = None, num_predict: int | None = None,
                      timeout_s: float | None = None) -> Runnable:
    """JSON 출력 고정(format="json") ChatOllama. 타임아웃은 httpx 읽기 대기에 적용된다."""
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        num_ctx=num_ctx or settings.llm_num_ctx,
        num_predict=num_predict or NUM_PREDICT,
        format="json",
        keep_alive=settings.ollama_keep_alive,
        client_kwargs={"timeout": timeout_s or settings.llm_timeout_s},
    )


def llm_factory(settings: Settings) -> Callable[[float], Runnable]:
    """체인 빌더가 시도(attempt)마다 온도를 바꿔 호출할 수 있는 팩토리."""
    return lambda temperature: build_chat_ollama(settings, temperature)


def report_llm_factory(settings: Settings) -> Callable[[float], Runnable]:
    """리포트 워커용: 더 긴 컨텍스트/출력/타임아웃 (면접 중 질문 생성 설정과 분리)."""
    return lambda temperature: build_chat_ollama(settings, temperature, num_ctx=settings.report_num_ctx,
                                                 num_predict=settings.report_num_predict, timeout_s=settings.report_llm_timeout_s)


def extract_llm_factory(settings: Settings) -> Callable[[float], Runnable]:
    """이력서 구조화 추출용: 긴 JSON 을 끝까지 쓰도록 출력 한도와 대기 시간을 면접용(256토큰·8초)과 분리한다."""
    return lambda temperature: build_chat_ollama(settings, temperature, num_predict=settings.resume_extract_num_predict,
                                                 timeout_s=settings.resume_extract_timeout_s)
