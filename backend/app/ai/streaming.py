"""LLM JSON 스트림에서 필드가 완성되는 즉시 추출 (TRD §2.4 핵심 지연 최적화).

`format=json` 출력은 키 순서가 고정(needed, reason, grounding_keywords, question, evidence)이므로, `question` 문자열이
닫히는 시점에는 앞선 필드가 모두 확정되어 있다. 이때 G2·G4·G5·G6 을 검증한 뒤 JSON 전체 완성을 기다리지 않고 TTS 를 시작한다.
"""
from __future__ import annotations

import json
import re
from typing import Any


from app.schemas.ai import FollowupDecision

_DECODER = json.JSONDecoder()
_KEYS = ("needed", "reason", "grounding_keywords", "question")


class StreamingDecisionParser:
    """청크를 누적하며 최상위 키의 값이 *완결*되는 순간 필드를 확정한다 (불완전한 값은 raw_decode 가 실패하므로 안전)."""

    def __init__(self) -> None:
        self.buffer = ""
        self.fields: dict[str, Any] = {}

    def feed(self, chunk: str) -> None:
        self.buffer += chunk
        for key in _KEYS:
            if key in self.fields:
                continue
            m = re.search(rf'(?<!\\)"{key}"\s*:\s*', self.buffer)  # 이스케이프된 따옴표 안의 가짜 키는 무시
            if not m:
                continue
            try:
                value, _end = _DECODER.raw_decode(self.buffer, m.end())
            except json.JSONDecodeError:
                continue  # 값이 아직 다 도착하지 않음
            self.fields[key] = value

    @property
    def ready(self) -> bool:
        """TTS 시작 전 검증에 필요한 필드가 모두 도착했는가.

        needed=false 면 question 이 필요 없으므로 needed·reason 만으로 충분하다 (꼬리질문 생략 결정).
        """
        f = self.fields
        if "needed" not in f or "reason" not in f:
            return False
        if f["needed"] is False:
            return True
        return "grounding_keywords" in f and "question" in f

    def partial_decision(self) -> FollowupDecision:
        """도착한 필드로 만든 결정. evidence 는 아직 없다. 일관성 위반이면 ValidationError(→ G1)."""
        f = self.fields
        return FollowupDecision.model_validate({
            "needed": f["needed"], "reason": f["reason"],
            "grounding_keywords": f.get("grounding_keywords") or [] if f["needed"] else [],
            "question": f.get("question") if f["needed"] else None,
            "evidence": [],
        })
