"""MainQuestion LCEL 체인 + Guardrail 생성 (TRD §3.4). prompt | llm | PydanticOutputParser(MainQuestion)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import Runnable

from app.ai.chains.prompts import MainQuestionInputs, main_question_prompt
from app.ai.guardrail import (MAX_ATTEMPTS, GenerationResult, GroundingContext, GuardrailEventSink, generate_with_guardrail,
                              verify_all)
from app.schemas.ai import MainQuestion


def build_main_question_chain(llm: Runnable) -> Runnable:
    parser = PydanticOutputParser(pydantic_object=MainQuestion)
    return main_question_prompt().partial(format_instructions=parser.get_format_instructions()) | llm | parser


async def generate_main_question(
    llm_factory: Callable[[float], Runnable],
    inputs: MainQuestionInputs,
    ctx: GroundingContext,
    *,
    fallback: Callable[[], MainQuestion | Awaitable[MainQuestion]] | None,
    sink: GuardrailEventSink | None = None,
    timeout_s: float | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    session_id: Any = None,
    turn_id: Any = None,
) -> GenerationResult[MainQuestion]:
    """메인 질문 생성. 3회 검증 실패 시 `fallback`(질문 뱅크의 미사용 후보 등)으로 대체한다 (TRD §3.5)."""
    return await generate_with_guardrail(
        lambda temperature: build_main_question_chain(llm_factory(temperature)),
        inputs.to_vars(), lambda r: verify_all(r, ctx),
        chain_name="main_question", fallback=fallback, max_attempts=max_attempts, timeout_s=timeout_s,
        sink=sink, session_id=session_id, turn_id=turn_id)
