"""테스트용 가짜 엔진. 실제 모델 없이 재시도·백오프·스트리밍 순서를 결정적으로 검증한다."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.runnables import Runnable

from app.ai.stt.base import SttResult
from app.interview.brain import FollowupContext, QuestionDraft, SessionConfig
from app.schemas.ai import FollowupDecision


# ── LLM ──────────────────────────────────────────────────────────────────────
class Stall(str):
    """astream 에서 이 텍스트를 흘린 뒤 더 이상 진행하지 않는다(응답 중단·타임아웃 시나리오). ainvoke 에서는 일반 문자열."""


class Truncated(str):
    """출력 한도(done_reason=length)에 걸려 끊긴 응답. ainvoke/invoke 의 메타데이터에 done_reason 을 싣는다."""


class ScriptedLLM(Runnable):
    """호출될 때마다 스크립트의 다음 항목을 소비한다. str 은 응답 본문, Exception 은 그대로 던진다.

    프롬프트와 온도를 기록해 재시도 사유 주입·온도 하향을 검증할 수 있다. astream 은 chunk_size 글자씩 흘려 스트리밍을 흉내 낸다.
    """

    def __init__(self, owner: ScriptedFactory, temperature: float):
        self.owner, self.temperature = owner, temperature

    def _next(self, input_: Any) -> str:
        msgs = input_.to_messages() if hasattr(input_, "to_messages") else input_
        self.owner.calls.append({"temperature": self.temperature, "prompt": "\n".join(m.content for m in msgs)})
        item = self.owner.script.pop(0) if self.owner.script else self.owner.default
        if isinstance(item, BaseException):
            raise item
        return item

    @staticmethod
    def _msg(text: str) -> AIMessage:
        return AIMessage(content=text, response_metadata={"done_reason": "length"} if isinstance(text, Truncated) else {})

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:  # noqa: A002
        return self._msg(self._next(input))

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> AIMessage:  # noqa: A002
        if self.owner.delay:
            await asyncio.sleep(self.owner.delay)
        return self._msg(self._next(input))

    async def astream(self, input: Any, config: Any = None, **kwargs: Any) -> AsyncIterator[AIMessageChunk]:  # noqa: A002
        text = self._next(input)
        size = self.owner.chunk_size
        for i in range(0, len(text), size):
            self.owner.events.append(("chunk", i))
            if self.owner.delay:
                await asyncio.sleep(self.owner.delay)
            yield AIMessageChunk(content=text[i:i + size])
            await asyncio.sleep(0)
        if isinstance(text, Stall):
            await asyncio.sleep(3600)  # 중단된 스트림


@dataclass
class ScriptedFactory:
    script: list[Any] = field(default_factory=list)
    default: Any = "{}"
    chunk_size: int = 6
    delay: float = 0.0
    calls: list[dict] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)

    def __call__(self, temperature: float) -> Runnable:
        return ScriptedLLM(self, temperature)

    @property
    def temperatures(self) -> list[float]:
        return [c["temperature"] for c in self.calls]


def followup_json(question: str | None = "Redis 캐시 무효화는 어떻게 처리하셨나요?", keywords: list[str] | None = None,
                  needed: bool = True, reason: str = "ambiguous", evidence: list[dict] | None = None) -> str:
    """TRD 확정 키 순서: needed, reason, grounding_keywords, question, evidence."""
    return json.dumps({"needed": needed, "reason": reason if needed else "none",
                       "grounding_keywords": keywords if keywords is not None else ["Redis", "캐시"],
                       "question": question if needed else None, "evidence": evidence or []}, ensure_ascii=False)


def main_json(question: str = "주문 조회 성능을 어떻게 개선하셨는지 설명해 주세요.", category: str = "기술", evidence: list[dict] | None = None) -> str:
    return json.dumps({"question": question, "category": category, "evidence": evidence or []}, ensure_ascii=False)


# ── 임베딩 ───────────────────────────────────────────────────────────────────
class HashEmbedder:
    """문자 2-gram 해시 BoW 를 L2 정규화한 결정적 임베더. 겹치는 글자가 많을수록 코사인 유사도가 높다."""

    def __init__(self, dim: int = 256):
        self.dim, self.unloaded, self.calls = dim, 0, 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out = []
        for t in texts:
            v = [0.0] * self.dim
            s = "".join(t.split()).lower()
            for i in range(max(len(s) - 1, 1)):
                v[int(hashlib.md5(s[i:i + 2].encode()).hexdigest(), 16) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out

    def unload(self) -> None:
        self.unloaded += 1


# ── STT / TTS ────────────────────────────────────────────────────────────────
class FakeSTT:
    model_name = "fake-stt"

    def __init__(self, texts: list[str] | None = None, fail: bool = False, delay: float = 0.0):
        self.texts, self.fail, self.delay = list(texts or ["Redis로 캐시를 붙여서 속도를 올렸어요"]), fail, delay
        self.calls: list[int] = []

    async def transcribe_pcm(self, pcm: bytes, *, initial_prompt: str | None = None) -> SttResult:
        self.calls.append(len(pcm))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("stt boom")
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return SttResult(text, -0.3, 0.05)


class FakeTTS:
    format = "wav"

    def __init__(self, chunks: int = 3, fail: bool = False):
        self.chunks, self.fail, self.texts = chunks, fail, []

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        self.texts.append(text)
        if self.fail:
            raise RuntimeError("tts boom")
        for i in range(self.chunks):
            yield bytes([i]) * 8


# ── 두뇌 ─────────────────────────────────────────────────────────────────────
class FakeBrain:
    """질문 목록과 꼬리질문 결정을 직접 지정한다. streaming=True 면 on_question_ready 콜백을 호출해 스트리밍 TTS 경로를 흉내 낸다."""

    def __init__(self, mains: list[str] | None = None, followups: list[FollowupDecision | Exception] | None = None,
                 total_main: int = 2, max_followups: int = 2, coding: bool = False, streaming: bool = True,
                 answer_limit: int = 60, triggers: dict[str, bool] | None = None):
        self.mains = list(mains or [f"{i + 1}번째 질문입니다. 설명해 주세요." for i in range(total_main)])
        self.followups = list(followups or [])
        self.cfg = SessionConfig(total_main, answer_limit, max_followups,
                                 triggers or {"trigger_ambiguous": True, "trigger_contradiction": True, "trigger_stt_unclear": True},
                                 coding, 3600 if coding else None, True)
        self.streaming, self.main_calls, self.followup_ctxs = streaming, [], []
        self.code_followups: list[FollowupDecision | Exception] = []

    async def load_config(self, session_id: Any) -> SessionConfig:
        return self.cfg

    async def next_main_question(self, session_id: Any, index: int, asked: list[str]) -> QuestionDraft:
        self.main_calls.append(index)
        return QuestionDraft(self.mains[index] if index < len(self.mains) else f"추가 질문 {index}입니다. 말씀해 주세요.",
                             category="기술")

    async def decide_code_followup(self, ctx, asked, used, max_followups, session_id):  # noqa: ANN001, ANN201
        self.code_ctxs = getattr(self, "code_ctxs", [])
        self.code_ctxs.append(ctx)
        self.code_histories = getattr(self, "code_histories", [])
        self.code_histories.append(list(ctx.history))  # 호출 시점의 스냅샷 (ctx 는 가변)
        item = self.code_followups.pop(0) if self.code_followups else FollowupDecision.skip()
        if isinstance(item, Exception):
            raise item
        return item

    async def decide_followup(self, ctx: FollowupContext, on_question_ready):  # noqa: ANN001, ANN201
        self.followup_ctxs.append(ctx)
        item = self.followups.pop(0) if self.followups else FollowupDecision.skip()
        if isinstance(item, Exception):
            raise item
        if item.needed and self.streaming:
            await on_question_ready(item)
        return item, bool(item.needed and self.streaming)


class FakeSandbox:
    """도커 없이 채점 로직을 검증한다. 소스에 든 표지로 동작을 흉내 낸다: WRONG→오답, LOOP→시간 초과, BOOM→런타임 오류, SYNTAX→컴파일 오류, 그 외→정답."""

    def __init__(self) -> None:
        from app.coding.problems import PROBLEMS

        self.answers = {c.stdin: c.expected for p in PROBLEMS for c in p.cases}
        self.calls = 0

    async def run(self, language: str, source: str, stdin: str, *, time_limit_s: float = 3.0):  # noqa: ANN201
        from app.coding.judge import RunResult

        self.calls += 1
        if "SYNTAX" in source:
            return RunResult(1, stderr="SyntaxError: invalid syntax", compile_error=True)
        if "LOOP" in source:
            return RunResult(-9, elapsed_ms=int(time_limit_s * 1000), timed_out=True)
        if "BOOM" in source:
            return RunResult(1, stderr="Traceback ... ZeroDivisionError", elapsed_ms=20)
        if "WRONG" in source:
            return RunResult(0, stdout="wrong\n", elapsed_ms=15)
        return RunResult(0, stdout=self.answers[stdin] + "\n", elapsed_ms=12)

    async def analyze(self, language: str, source: str):  # noqa: ANN201
        from app.coding.analysis import analyze_source

        return await analyze_source(self, language, source)
