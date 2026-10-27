"""리포트 체인 (TRD §3.4 report_chain): 턴별 채점 + 총평/TOP3. 모든 출력은 Pydantic 파서와 Guardrail(G1·G3·G4)을 통과해야 한다.

* 턴 채점(`evaluate_turn`): 루브릭 level(1~5) + 답변 원문 인용(evidence). 3회 실패 시 그 턴은 *채점 제외*(None) — 틀린 점수보다 무점수가 안전.
* 총평(`write_narrative`): 3회 실패 시 호출자가 결정적(규칙 기반) 대체 문구를 쓴다 (None 반환).
LLM 연결 실패/타임아웃은 `LLMUnavailable` 로 올려 워커가 잡을 재시도하게 한다.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import Runnable

from app.ai.chains.report_prompts import (CRITERION_LABELS, TurnEvalInputs, eval_prompt, narrative_prompt)
from app.ai.chains.prompts import defang
from app.ai.errors import GuardrailError
from app.ai.guardrail import (GroundingContext, GuardrailEventSink, check_evidence, check_forbidden, generate_with_guardrail)
from app.schemas.ai import Evidence, ReportNarrative, TurnEvaluation

CRITERIA = ("concept_understanding", "logic", "delivery", "attitude", "job_expertise")
EXCERPT_CHARS = 280


def _check_texts(texts: Sequence[str]) -> None:
    """G4 (평가 문장 버전): 코멘트·총평에 인적 속성 언급 금지 (NFR-Q4)."""
    for t in texts:
        check_forbidden(t)


def verify_turn_evaluation(ev: TurnEvaluation, ctx: GroundingContext) -> None:
    evidences = list(ev.evidence)
    if ev.highlight is not None:
        evidences.append(Evidence(source="answer", ref=ev.evidence[0].ref, quote=ev.highlight.quote))
    check_evidence(evidences, ctx)  # G3: 인용이 답변 원문에 있어야 한다
    _check_texts([getattr(ev, c).comment for c in CRITERIA] + ([ev.highlight.reason] if ev.highlight else []))


def _prune(items: list, ctx: GroundingContext) -> list:
    """원문과 일치하는 인용만 남기고, 인용이 하나도 남지 않은 항목은 버린다 (NFR-Q1: 근거 없는 코멘트 비표시)."""
    kept = []
    for it in items:
        it.evidence = [e for e in it.evidence if _grounded(e, ctx)]
        if it.evidence:
            kept.append(it)
    return kept


def _grounded(e: Evidence, ctx: GroundingContext) -> bool:
    try:
        check_evidence([e], ctx)
        return True
    except GuardrailError:
        return False


def verify_narrative(n: ReportNarrative, ctx: GroundingContext) -> None:
    """7B 모델은 인용을 자주 바꿔 쓴다. 전체를 버리고 재시도하기 전에, 검증된 근거가 있는 항목만 남긴다(제자리 수정).
    강점/개선점이 각각 1개도 남지 않을 때만 G3 실패로 재시도한다."""
    n.strengths, n.improvements = _prune(n.strengths, ctx), _prune(n.improvements, ctx)
    if not n.strengths or not n.improvements:
        raise GuardrailError("G3", "강점과 개선점마다 [질문별 답변 발췌]에 있는 문장을 글자 그대로 인용한 evidence 가 하나 이상 있어야 합니다")
    _check_texts([n.summary] + [f"{i.title} {i.detail}" for i in (*n.strengths, *n.improvements)])


def _chain(llm: Runnable, prompt: Any, model: type) -> Runnable:
    parser = PydanticOutputParser(pydantic_object=model)
    return prompt.partial(format_instructions=parser.get_format_instructions()) | llm | parser


async def evaluate_turn(llm_factory: Callable[[float], Runnable], inputs: TurnEvalInputs, *, sink: GuardrailEventSink | None = None,
                        timeout_s: float | None = None, session_id: Any = None, turn_id: Any = None) -> TurnEvaluation | None:
    """None = 3회 검증 실패(이 턴은 채점 제외)."""
    ctx = GroundingContext(answer_text=inputs.answer, sources={inputs.answer_ref: inputs.answer})
    res = await generate_with_guardrail(
        lambda t: _chain(llm_factory(t), eval_prompt(), TurnEvaluation), inputs.to_vars(), lambda r: verify_turn_evaluation(r, ctx),
        chain_name="report", fallback=lambda: None, timeout_s=timeout_s, sink=sink, session_id=session_id, turn_id=turn_id)
    return None if res.fell_back else res.value


async def write_narrative(llm_factory: Callable[[float], Runnable], *, job_title: str, criteria: Mapping[str, float],
                          turn_summaries: str, excerpts: Mapping[str, str], sink: GuardrailEventSink | None = None,
                          timeout_s: float | None = None, session_id: Any = None) -> ReportNarrative | None:
    """excerpts: ref("turn:{id}") → 답변 원문. 프롬프트에는 앞 280자만 싣지만 검증(G3)은 원문 전체에 대해 한다."""
    ctx = GroundingContext(sources=dict(excerpts))
    variables = {
        "job_title": job_title,
        "criteria": "\n".join(f"- {CRITERION_LABELS[k]}: {v:.0f}" for k, v in criteria.items()),
        "turn_summaries": turn_summaries,
        "excerpts": "\n".join(f"[ref={ref}] {defang(text)[:EXCERPT_CHARS]}" for ref, text in excerpts.items()),
    }
    res = await generate_with_guardrail(
        lambda t: _chain(llm_factory(t), narrative_prompt(), ReportNarrative), variables, lambda r: verify_narrative(r, ctx),
        chain_name="report", fallback=lambda: None, timeout_s=timeout_s, sink=sink, session_id=session_id)
    return None if res.fell_back else res.value


_ = GuardrailError
