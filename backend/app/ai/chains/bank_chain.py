"""JD 기반 질문 뱅크 후보 생성 (TRD §3.4 JobQuestionBank 체인). 출력은 Pydantic 파서 + Guardrail(G4 인적 속성, G5 중복, G6 형식)을 통과한 항목만 남긴다."""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from app.ai.chains.prompts import SYSTEM_RULES, defang
from app.ai.errors import GuardrailError
from app.ai.guardrail import GuardrailEventSink, check_duplicate, check_forbidden, check_form, generate_with_guardrail
from app.schemas.ai import BankItem, QuestionBank

TARGET = 20
CATEGORIES = "기술, 문제해결, 협업, 인성, 직무 이해"
HUMAN = (
    "[직무] {title}\n[주요 업무]\n<untrusted>\n{duties}\n</untrusted>\n[지원 요건]\n<untrusted>\n{requirements}\n</untrusted>\n[우대 사항]\n<untrusted>\n{preferred}\n</untrusted>\n\n"
    "위 직무요건에 근거한 면접 질문 후보를 " + str(TARGET) + "개 만드세요. 각 질문은 서로 다른 관점이어야 하고, category 는 [" + CATEGORIES + "] 중 하나입니다.\n"
    "JSON 형식: {{\"items\": [{{\"question\": \"...\", \"category\": \"...\"}}]}}\n{retry_hint}"
)


def filter_valid(items: list[BankItem]) -> list[BankItem]:
    """G4·G6·G5 를 통과한 항목만, 먼저 나온 순서로 최대 TARGET 개."""
    out: list[BankItem] = []
    for it in items:
        try:
            check_forbidden(it.question)
            check_form(it.question)
            check_duplicate(it.question, [o.question for o in out])
        except GuardrailError:
            continue
        out.append(it)
    return out[:TARGET]


async def generate_bank(llm_factory: Callable[[float], Runnable], *, title: str, duties: str, requirements: str, preferred: str,
                        sink: GuardrailEventSink | None = None, timeout_s: float | None = None) -> list[BankItem]:
    """빈 목록이면 호출자가 '결과 0건 — JD 가 너무 짧음' 으로 처리한다. LLM 연결 실패는 LLMUnavailable."""
    parser = PydanticOutputParser(pydantic_object=QuestionBank)
    prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_RULES + "\n{format_instructions}"), ("human", HUMAN)]).partial(
        format_instructions=parser.get_format_instructions())

    def verify(r: QuestionBank) -> None:
        if not filter_valid(r.items):
            raise GuardrailError("G6", "형식을 지킨 질문이 하나도 없습니다. 한 문장 의문형 질문만 만드세요")

    res = await generate_with_guardrail(
        lambda t: prompt | llm_factory(t) | parser,
        {"title": title, "duties": defang(duties or "(없음)")[:1500], "requirements": defang(requirements or "(없음)")[:1500],
         "preferred": defang(preferred or "(없음)")[:600]}, verify, chain_name="question_bank", fallback=lambda: None,
        timeout_s=timeout_s, sink=sink)
    return [] if res.fell_back or res.value is None else filter_valid(res.value.items)
