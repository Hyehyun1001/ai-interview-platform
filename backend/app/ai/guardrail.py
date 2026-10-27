"""환각 방지 Guardrail 과 Retry/Fallback 오케스트레이션 (TRD §3.5).

검증 단계 (순서대로): G1 스키마 · G2 키워드 Grounding · G3 Evidence quote · G4 금칙어/인적 속성 · G5 중복 질문 · G6 길이/형식.
스트리밍 TTS 를 위해 TTS 시작 전(`verify_before_tts`: G2·G4·G5·G6)과 후(`verify_evidence`: G3)로 나눠 호출할 수 있다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable
from pydantic import ValidationError

from app.ai.errors import GuardrailError, LLMUnavailable
from app.schemas.ai import FollowupDecision, MainQuestion

log = logging.getLogger("app.ai.guardrail")

MAX_ATTEMPTS = 3
RETRY_TEMPERATURE = 0.3  # 재시도 온도 (2026-10-26 결정): 0.0 은 같은 프롬프트에 같은 출력을 반복시켜 G2·G6 재시도가 무의미했다
MAX_QUESTION_CHARS = 120
JACCARD_DUP_THRESHOLD = 0.6  # G5
EVIDENCE_MAX_EDIT_RATIO = 0.15  # G3
MIN_KEYWORD_CHARS = 2
_HAYSTACK_LIMIT = 8000  # G3 편집거리 계산 상한 (지연 방지)

T = TypeVar("T")

# ── 텍스트 정규화 ──────────────────────────────────────────────────────────────
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize_compact(text: str) -> str:
    """NFC + 소문자 + 공백·구두점 제거. 한국어 띄어쓰기 변이와 STT 공백 차이를 흡수한다."""
    return _NON_WORD.sub("", unicodedata.normalize("NFC", text).lower())


# 길이 내림차순으로 시도해 가장 긴 조사를 먼저 제거한다
_JOSA = sorted(
    ["으로써", "으로서", "에서는", "에게서", "에서도", "으로는", "으로도", "까지는", "이라고", "이라는", "에서", "에게", "한테", "께서",
     "으로", "까지", "부터", "처럼", "보다", "하고", "이랑", "이나", "라는", "이라", "라고", "은", "는", "이", "가", "을", "를", "의",
     "에", "도", "만", "로", "과", "와", "랑", "나"],
    key=len, reverse=True,
)
_JOSA_RE = re.compile("(?:" + "|".join(map(re.escape, _JOSA)) + ")$")


def strip_josa(token: str) -> str:
    """끝의 조사 1개를 제거한다 (형태소 분석기 없이 쓰는 근사). 과제거 위험은 호출부가 원형도 함께 비교해 흡수한다."""
    return _JOSA_RE.sub("", token)


_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_VERBISH = re.compile(r"(습니다|니다|어요|아요|고요|는데|했다|한다|이다|해서|하고|하며|하는|했던|하면)$")
_STOPWORDS = {"그냥", "그게", "이게", "저는", "제가", "정도", "이후", "때문", "다음", "그리고", "그래서", "하지만", "그런데", "자세히", "조금",
              "매우", "아주", "정말", "크게", "문제는", "것은", "부분", "경우", "생각", "관련", "통해"}


def candidate_keywords(text: str, limit: int = 25) -> list[str]:
    """답변에서 `grounding_keywords` 후보를 뽑는다 (조사·어미 제거, 중복 제거, 등장 순서 유지).

    7B 4비트 모델은 자유 서술로 키워드를 쓰게 하면 철자를 틀리거나("멱등성"→"멤전성") 질문 속 단어를 가져오는 일이 잦다.
    후보 목록에서 *고르게* 하면(제약된 선택) 옮겨 적기 오류가 크게 줄고, G2 는 그대로 최종 방어선으로 남는다.
    """
    seen: set[str] = set()
    out: list[str] = []
    for tok in _TOKEN.findall(unicodedata.normalize("NFC", text)):
        stem = strip_josa(tok) if re.search(r"[가-힣]", tok) else tok
        if len(stem) < MIN_KEYWORD_CHARS or stem.isdigit() or stem in _STOPWORDS or _VERBISH.search(stem):
            continue
        if stem.lower() in seen:
            continue
        seen.add(stem.lower())
        out.append(stem)
        if len(out) >= limit:
            break
    return out


# ── G2~G6 개별 검증 ────────────────────────────────────────────────────────────
@dataclass
class GroundingContext:
    """검증에 필요한 근거 텍스트 모음. 이 객체는 메모리에서만 쓰이며 저장하지 않는다."""

    answer_text: str = ""  # 지원자 STT 답변
    resume_text: str = ""  # 정규화된 이력서(JSON 문자열 또는 chunk 텍스트)
    asked_questions: Sequence[str] = ()
    sources: Mapping[str, str] = field(default_factory=dict)  # evidence ref -> 원문 ("turn:42", chunk_id)
    corpus_norm: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self.corpus_norm = normalize_compact(self.answer_text + " " + self.resume_text)


def check_keyword_grounding(keywords: Sequence[str], ctx: GroundingContext) -> None:
    """G2: 각 키워드가 답변/이력서 텍스트에 실제 포함되어야 한다 (조사 제거 후 비교)."""
    if not keywords:
        raise GuardrailError("G2", "grounding_keywords 가 비어 있습니다")
    for kw in keywords:
        raw = normalize_compact(kw)
        if len(raw) < MIN_KEYWORD_CHARS:
            raise GuardrailError("G2", f"키워드 '{kw}' 가 너무 짧습니다")
        candidates = [raw]
        stem = strip_josa(raw)
        if stem != raw and len(stem) >= MIN_KEYWORD_CHARS:  # 과제거(1글자 어간)는 후보에서 제외
            candidates.append(stem)
        if not any(c in ctx.corpus_norm for c in candidates):
            raise GuardrailError("G2", f"키워드 '{kw}' 가 지원자 답변/이력서에 없습니다. 답변에 실제로 나온 단어만 사용하세요")


def approx_substring_distance(needle: str, haystack: str) -> int:
    """needle 이 haystack 의 어떤 부분문자열과 가질 수 있는 최소 편집거리 (Sellers 알고리즘)."""
    m = len(needle)
    if m == 0:
        return 0
    prev = list(range(m + 1))
    best = prev[m]
    for ch in haystack:
        cur = [0]
        for i in range(1, m + 1):
            cur.append(min(prev[i] + 1, cur[i - 1] + 1, prev[i - 1] + (needle[i - 1] != ch)))
        prev = cur
        if prev[m] < best:
            best = prev[m]
            if best == 0:
                break
    return best


def _quote_matches(needle: str, source: str) -> bool:
    hay = normalize_compact(source)[:_HAYSTACK_LIMIT]
    if not needle:
        return False
    return needle in hay or approx_substring_distance(needle, hay) / len(needle) <= EVIDENCE_MAX_EDIT_RATIO


def check_evidence(evidence: Sequence[Any], ctx: GroundingContext) -> None:
    """G3: evidence.quote 가 제공된 근거 원문에 (공백 정규화, 편집거리 ≤ 15%) 부분 일치해야 한다.

    7B 모델은 ref 에 chunk_id 대신 제목("주문 조회 성능 개선")을 쓰는 일이 잦다(실제 E2E 관찰). ref 가 근거 목록에 없으면 인용문이
    *제공된 어느 원문에든* 들어 있는지 확인하고, 있으면 ref 를 그 원문의 키로 바로잡는다. 인용이 어디에도 없으면 실패 — 환각 차단은 유지된다.
    """
    for ev in evidence:
        needle = normalize_compact(ev.quote)
        if not needle:
            raise GuardrailError("G3", "evidence.quote 가 비어 있습니다")
        source = ctx.sources.get(ev.ref)
        if source is not None:
            if not _quote_matches(needle, source):
                raise GuardrailError("G3", f"evidence.quote 가 '{ev.ref}' 원문과 일치하지 않습니다. 원문에서 그대로 인용하세요")
            continue
        found = next((k for k, text in ctx.sources.items() if _quote_matches(needle, text)), None)
        if found is None:
            raise GuardrailError("G3", f"evidence.ref '{ev.ref}' 가 제공된 근거에 없고 인용문도 어느 근거에서도 찾을 수 없습니다. ref 는 근거 목록의 id 를 그대로 쓰세요")
        ev.ref = found


# 인적 속성·사생활 질문 사전 (TRD G4). 오탐을 줄이기 위해 IT 용어와 겹치는 표현("나이브", "장애 대응", "키")은 제외한다.
_FORBIDDEN_PATTERNS = [
    r"성별", r"나이(?!브)", r"연령", r"몇\s*살", r"생년월일", r"결혼", r"미혼", r"기혼", r"배우자", r"남편", r"아내", r"자녀", r"임신",
    r"출산", r"육아\s*계획", r"출신지", r"고향", r"어디\s*(?:에서\s*)?(?:태어|자랐|출신)", r"종교", r"신앙", r"가족\s*(?:관계|구성|사항)",
    r"부모님", r"형제", r"지지\s*정당", r"장애인", r"신체\s*장애", r"장애\s*여부", r"몸무게", r"체중", r"혈액형", r"외모", r"연애",
    r"애인", r"(?:남자|여자)\s*친구",
]
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_PATTERNS))


def check_forbidden(question: str) -> None:
    """G4: 성별·나이·결혼·가족·출신지·종교 등 인적 속성에 관한 질문 금지 (NFR-Q4)."""
    m = _FORBIDDEN_RE.search(unicodedata.normalize("NFC", question))
    if m:
        raise GuardrailError("G4", f"'{m.group(0)}' 등 인적 속성에 관한 질문은 할 수 없습니다")


def _ngrams(text: str, n: int = 3) -> set[str]:
    return {text[i:i + n] for i in range(max(len(text) - n + 1, 0))}


def jaccard(a: str, b: str, n: int = 3) -> float:
    if a == b:
        return 1.0 if a else 0.0
    ga, gb = _ngrams(a, n), _ngrams(b, n)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def check_duplicate(question: str, asked: Sequence[str]) -> None:
    """G5: 이미 한 질문과 문자 3-gram Jaccard ≥ 0.6 이면 실패 (면접 중 임베딩 회피)."""
    q = normalize_compact(question)
    for prev in asked:
        if jaccard(q, normalize_compact(prev)) >= JACCARD_DUP_THRESHOLD:
            raise GuardrailError("G5", "이미 한 질문과 거의 같습니다. 다른 관점의 질문을 만드세요")


_SENTENCE_SPLIT = re.compile(r"(?<=[.?!。？！])\s+")
# 의문형 또는 정중한 요청형("…해 주세요")을 허용 — 면접 질문 관행. 평서형("…했습니다.")은 거부
_QUESTION_END = re.compile(r"(?:[?？]|(?:까요|나요|가요|니까|세요|죠|까|요))[.]?\s*$")


def check_form(question: str) -> None:
    """G6: 한 문장, ≤ 120자, 의문형 또는 정중한 요청형."""
    q = question.strip()
    if not q:
        raise GuardrailError("G6", "질문이 비어 있습니다")
    if len(q) > MAX_QUESTION_CHARS:
        raise GuardrailError("G6", f"질문이 {MAX_QUESTION_CHARS}자를 넘습니다 ({len(q)}자)")
    if "\n" in q or len(_SENTENCE_SPLIT.split(q)) > 1:
        # 재시도는 온도 0.0 이라 같은 프롬프트에는 같은 출력이 반복된다 — 직전 문장을 보여 주고 무엇을 어떻게 고칠지 구체적으로 지시한다
        raise GuardrailError("G6", f"직전 질문 '{q[:100]}' 은 문장이 둘 이상입니다. 앞의 설명·평가 문장(마침표로 끝나는 문장)을 모두 빼고 "
                                   "물음표로 끝나는 질문 한 문장만 다시 쓰세요. 필요한 맥락은 질문 문장 안에 녹이세요")
    if not _QUESTION_END.search(q):
        raise GuardrailError("G6", "질문은 의문형 또는 정중한 요청형('~하셨나요?', '~해 주세요')으로 끝나야 합니다")


# ── 조합 ──────────────────────────────────────────────────────────────────────
def verify_before_tts(result: FollowupDecision | MainQuestion, ctx: GroundingContext) -> None:
    """TTS 시작 전에 끝나야 하는 검증: G2(꼬리질문만)·G4·G5·G6. G1 은 파서가 이미 수행."""
    if isinstance(result, FollowupDecision):
        if not result.needed:
            return
        check_keyword_grounding(result.grounding_keywords, ctx)
        question = result.question or ""
    else:
        question = result.question
    check_forbidden(question)
    check_duplicate(question, ctx.asked_questions)
    check_form(question)


def verify_evidence(result: FollowupDecision | MainQuestion, ctx: GroundingContext) -> None:
    """G3. 스트리밍 경로에서는 TTS 재생 중 후속 검증한다."""
    if isinstance(result, FollowupDecision) and not result.needed:
        return
    check_evidence(result.evidence, ctx)


def verify_all(result: FollowupDecision | MainQuestion, ctx: GroundingContext) -> None:
    """엄격 모드(비스트리밍): G2~G6 를 TRD 순서(G2→G3→G4→G5→G6)대로 모두 검증."""
    if isinstance(result, FollowupDecision):
        if not result.needed:
            return
        check_keyword_grounding(result.grounding_keywords, ctx)
    check_evidence(result.evidence, ctx)
    question = result.question or "" if isinstance(result, FollowupDecision) else result.question
    check_forbidden(question)
    check_duplicate(question, ctx.asked_questions)
    check_form(question)


# ── 이벤트 기록 ───────────────────────────────────────────────────────────────
@dataclass
class GuardrailEventRecord:
    chain: str  # main_question | followup | report | resume_extract
    attempt: int
    check_id: str  # G1~G6, 성공 시 "OK"
    reason: str | None  # 고정 문구만 (PII 금지)
    outcome: str  # retry | fallback | passed
    session_id: Any = None
    turn_id: Any = None


class GuardrailEventSink(Protocol):
    async def record(self, event: GuardrailEventRecord) -> None: ...


class ListSink:
    """테스트·로컬용 메모리 싱크."""

    def __init__(self) -> None:
        self.events: list[GuardrailEventRecord] = []

    async def record(self, event: GuardrailEventRecord) -> None:
        self.events.append(event)


class DbGuardrailEventSink:
    """guardrail_events 테이블에 저장 (KPI '꼬리질문 근거 일치율' 산출용)."""

    def __init__(self, sessionmaker: Any):
        self._sm = sessionmaker

    async def record(self, event: GuardrailEventRecord) -> None:
        from app.models.ops import GuardrailEvent

        async with self._sm() as db:
            db.add(GuardrailEvent(
                session_id=event.session_id, turn_id=event.turn_id, chain=event.chain, attempt=event.attempt,
                check_id=event.check_id, reason=(event.reason or "")[:300] or None, outcome=event.outcome))
            await db.commit()


# ── 생성 + 검증 + 재시도 + 대체 ────────────────────────────────────────────────
try:  # ollama 클라이언트 예외 (langchain-ollama 의존성)
    from ollama import ResponseError as _OllamaResponseError
except ImportError:  # pragma: no cover
    _OllamaResponseError = ConnectionError  # type: ignore[misc,assignment]

LLM_TRANSPORT_ERRORS: tuple[type[BaseException], ...] = (httpx.TransportError, ConnectionError, _OllamaResponseError)


@dataclass
class GenerationResult(Generic[T]):
    value: T
    attempts: int  # 실제 LLM 호출 횟수
    fell_back: bool  # True 면 대체 동작(꼬리질문 생략 / 질문 뱅크 대체)이 사용됨
    failures: list[GuardrailEventRecord] = field(default_factory=list)


def _to_guardrail_error(exc: BaseException) -> GuardrailError:
    """파싱/검증 예외를 G1 로 변환. 상세 메시지에는 필드 위치만 넣고 LLM 출력 원문은 넣지 않는다."""
    if isinstance(exc, GuardrailError):
        return exc
    cause = exc.__cause__ if isinstance(exc, OutputParserException) else exc
    if isinstance(cause, ValidationError):
        locs = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in cause.errors()[:3])
        return GuardrailError("G1", f"출력 JSON 스키마 위반 — {locs}")
    return GuardrailError("G1", "출력이 올바른 JSON 이 아닙니다. 스키마에 맞는 JSON 객체 하나만 출력하세요")


def retry_hint(last_error: GuardrailError | None) -> str:
    if last_error is None:
        return ""
    return f"\n\n[이전 시도 실패 사유]\n{last_error.message[:300]}"


async def _maybe_await(value: Any) -> Any:
    return await value if isinstance(value, Awaitable) else value


async def _emit(sink: GuardrailEventSink | None, event: GuardrailEventRecord) -> None:
    if sink is None:
        return
    try:
        await sink.record(event)
    except Exception as e:  # noqa: BLE001  로그 실패가 면접 진행을 막으면 안 된다
        log.warning("guardrail event sink failed: %s", type(e).__name__)


AttemptFn = Callable[[int, float, str], Awaitable[Any]]  # (attempt, temperature, retry_hint) -> 검증을 통과한 결과


async def run_with_guardrail(
    attempt_fn: AttemptFn,
    *,
    chain_name: str,
    fallback: Callable[[], Any] | None,
    max_attempts: int = MAX_ATTEMPTS,
    sink: GuardrailEventSink | None = None,
    session_id: Any = None,
    turn_id: Any = None,
) -> GenerationResult[Any]:
    """시도 → 검증 실패 시 사유를 프롬프트에 주입해 재시도 (최대 max_attempts) → 모두 실패하면 대체 동작.

    * 온도: 1회차 0.2, 재시도는 0.3 (TRD §3.5 — 0.0 은 같은 출력을 반복시켜 재시도 효과가 없었다).
    * 모두 실패하면 `fallback()` 결과를 반환한다 — 꼬리질문은 *생략*, 메인 질문은 질문 뱅크 후보로 대체.
      fallback 이 None 이면 마지막 GuardrailError 를 그대로 올린다.
    * LLM 연결 실패/타임아웃은 콘텐츠 실패가 아니므로 재시도 없이 LLMUnavailable 로 올린다 (경량 모드 판단은 호출자).
    * `attempt_fn` 은 검증(G1~G6)을 통과한 결과를 반환하거나 GuardrailError/ValidationError/OutputParserException 을 던져야 한다.
    """
    last_error: GuardrailError | None = None
    failures: list[GuardrailEventRecord] = []
    for attempt in range(1, max_attempts + 1):
        temperature = 0.2 if attempt == 1 else RETRY_TEMPERATURE
        try:
            result = await attempt_fn(attempt, temperature, retry_hint(last_error))
        except asyncio.TimeoutError as e:
            raise LLMUnavailable("LLM 응답 시간 초과") from e
        except LLM_TRANSPORT_ERRORS as e:
            raise LLMUnavailable(f"LLM 연결 실패: {type(e).__name__}") from e
        except (ValidationError, OutputParserException, GuardrailError) as e:
            last_error = _to_guardrail_error(e)
            record = GuardrailEventRecord(chain_name, attempt, last_error.check_id, last_error.public_reason,
                                          "fallback" if attempt == max_attempts else "retry", session_id, turn_id)
            failures.append(record)
            await _emit(sink, record)
            log.info("guardrail %s failed chain=%s attempt=%d/%d", last_error.check_id, chain_name, attempt, max_attempts)
            continue
        await _emit(sink, GuardrailEventRecord(chain_name, attempt, "OK", None, "passed", session_id, turn_id))
        return GenerationResult(result, attempt, False, failures)

    if fallback is None:
        assert last_error is not None
        raise last_error
    return GenerationResult(await _maybe_await(fallback()), max_attempts, True, failures)


async def generate_with_guardrail(
    build_chain: Callable[[float], Runnable],
    inputs: dict[str, Any],
    verify: Callable[[Any], None],
    *,
    chain_name: str,
    fallback: Callable[[], Any] | None,
    max_attempts: int = MAX_ATTEMPTS,
    timeout_s: float | None = None,
    sink: GuardrailEventSink | None = None,
    session_id: Any = None,
    turn_id: Any = None,
) -> GenerationResult[Any]:
    """비스트리밍 경로: `build_chain(temperature)` 가 만든 체인(파서 포함)을 호출하고 `verify` 로 검증한다."""

    async def attempt_fn(_attempt: int, temperature: float, hint: str) -> Any:
        call = build_chain(temperature).ainvoke({**inputs, "retry_hint": hint})
        result = await (asyncio.wait_for(call, timeout_s) if timeout_s else call)
        verify(result)
        return result

    return await run_with_guardrail(attempt_fn, chain_name=chain_name, fallback=fallback, max_attempts=max_attempts,
                                    sink=sink, session_id=session_id, turn_id=turn_id)
