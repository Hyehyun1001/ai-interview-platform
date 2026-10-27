"""FollowupDecision LCEL 체인과 Guardrail 생성 — 비스트리밍/스트리밍 두 경로 (TRD §3.4, §2.4).

스트리밍 경로(`generate_followup_streaming`)가 운영 설계다: `question` 필드가 닫히는 즉시 G2·G4·G5·G6 을 검증하고
통과하면 `on_question_ready` 로 TTS 를 시작한다. 이미 음성이 나간 시도는 되돌릴 수 없으므로 **재시도하지 않고** 마무리하며,
G3(evidence)는 후속 검증해 실패하면 질문은 유지한 채 근거만 제거한다.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from app.ai.chains.prompts import FollowupInputs, followup_prompt
from app.ai.errors import GuardrailError
from app.ai.guardrail import (MAX_ATTEMPTS, GenerationResult, GroundingContext, GuardrailEventRecord, GuardrailEventSink,
                              _emit, _to_guardrail_error, generate_with_guardrail, run_with_guardrail, verify_all,
                              verify_before_tts, verify_evidence)
from app.ai.streaming import StreamingDecisionParser
from app.schemas.ai import FollowupDecision


def _parser() -> PydanticOutputParser:
    return PydanticOutputParser(pydantic_object=FollowupDecision)


def build_followup_raw_chain(llm: Runnable) -> Runnable:
    """prompt | llm — 스트리밍 경로용 (파싱은 StreamingDecisionParser 가 담당)."""
    return followup_prompt().partial(format_instructions=_parser().get_format_instructions()) | llm


def build_followup_chain(llm: Runnable) -> Runnable:
    return build_followup_raw_chain(llm) | _parser()


async def generate_followup(
    llm_factory: Callable[[float], Runnable], inputs: FollowupInputs, ctx: GroundingContext, *,
    sink: GuardrailEventSink | None = None, timeout_s: float | None = None, max_attempts: int = MAX_ATTEMPTS,
    session_id: Any = None, turn_id: Any = None,
) -> GenerationResult[FollowupDecision]:
    """비스트리밍 경로. 3회 실패 시 꼬리질문을 *생략*한다 (FollowupDecision.skip())."""
    return await generate_with_guardrail(
        lambda t: build_followup_chain(llm_factory(t)), inputs.to_vars() | {"retry_hint": ""}, lambda r: verify_all(r, ctx),
        chain_name="followup", fallback=FollowupDecision.skip, max_attempts=max_attempts, timeout_s=timeout_s,
        sink=sink, session_id=session_id, turn_id=turn_id)


@dataclass
class StreamedFollowup:
    decision: FollowupDecision
    spoken_early: bool  # JSON 전체 완성 전에 TTS 가 시작되었는가
    evidence_dropped: bool  # G3/G1(후속) 실패로 근거만 제거했는가


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", chunk)
    return content if isinstance(content, str) else str(content)


async def generate_followup_streaming(
    llm_factory: Callable[[float], Runnable], inputs: FollowupInputs, ctx: GroundingContext, *,
    on_question_ready: Callable[[FollowupDecision], Awaitable[None]],
    sink: GuardrailEventSink | None = None, timeout_s: float | None = None, max_attempts: int = MAX_ATTEMPTS,
    session_id: Any = None, turn_id: Any = None,
) -> GenerationResult[StreamedFollowup]:
    base_vars = inputs.to_vars()
    final_parser = _parser()

    async def attempt_fn(attempt: int, temperature: float, hint: str) -> StreamedFollowup:
        stream = build_followup_raw_chain(llm_factory(temperature)).astream({**base_vars, "retry_hint": hint})
        parser = StreamingDecisionParser()
        partial: FollowupDecision | None = None
        spoken = False
        try:
            async with asyncio.timeout(timeout_s):
                async for chunk in stream:
                    parser.feed(_chunk_text(chunk))
                    if partial is None and parser.ready:
                        partial = parser.partial_decision()  # ValidationError → G1 (재시도)
                        verify_before_tts(partial, ctx)  # GuardrailError → 음성 시작 전이므로 재시도 가능
                        if not partial.needed:
                            break  # 꼬리질문 생략 결정 — 나머지 출력은 필요 없다
                        await on_question_ready(partial)  # 부분 결정(evidence 미포함)을 넘겨 호출자가 턴을 만들 수 있게 한다
                        spoken = True
        except TimeoutError:
            if not spoken:
                raise
            # 음성이 이미 나갔다면 질문은 유효하다. JSON 마무리만 포기하고 근거 없이 확정한다.
            return StreamedFollowup(partial, True, True)  # type: ignore[arg-type]
        finally:
            await stream.aclose()  # 조기 종료/실패 시 LLM 생성 중단

        if partial is None:  # 스트림이 끝났는데 필수 필드가 도착하지 않음
            raise _to_guardrail_error(OutputParserException("incomplete"))
        if not partial.needed:
            return StreamedFollowup(partial, False, False)
        try:  # 음성 이후의 후속 검증: 실패해도 질문은 유지하고 근거만 제거
            full = final_parser.parse(parser.buffer)
            verify_evidence(full, ctx)
            return StreamedFollowup(full, True, False)
        except (ValidationError, OutputParserException, GuardrailError) as e:
            err = _to_guardrail_error(e)
            await _emit(sink, GuardrailEventRecord("followup", attempt, err.check_id, err.public_reason, "passed", session_id, turn_id))
            return StreamedFollowup(partial, True, True)

    result = await run_with_guardrail(
        attempt_fn, chain_name="followup", fallback=lambda: StreamedFollowup(FollowupDecision.skip(), False, False),
        max_attempts=max_attempts, sink=sink, session_id=session_id, turn_id=turn_id)
    return result
