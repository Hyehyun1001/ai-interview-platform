"""AI 파이프라인 공통 예외."""
from __future__ import annotations

# G1~G6 별 공개용 사유. 이벤트 로그·DB 에는 이 문구만 저장한다 (사용자 발화·이력서 원문 금지, TRD §3.5).
PUBLIC_REASONS = {
    "G1": "출력 스키마 위반",
    "G2": "grounding 키워드가 근거 텍스트에 없음",
    "G3": "evidence quote 가 원문과 불일치",
    "G4": "금칙어/인적 속성 질문",
    "G5": "이미 한 질문과 중복",
    "G6": "길이/형식 위반",
}


class LLMUnavailable(Exception):
    """LLM 연결 실패·타임아웃. 콘텐츠 검증 실패(GuardrailError)와 구분한다 — 호출자가 경량 모드/꼬리질문 생략을 결정."""


class GuardrailError(Exception):
    """Guardrail 검증 실패.

    message: LLM 재시도 프롬프트에 주입하는 상세 사유 (메모리에서만 사용, 저장 금지).
    public_reason: 로그/DB 에 저장 가능한 고정 문구.
    """

    def __init__(self, check_id: str, message: str):
        super().__init__(f"{check_id}: {message}")
        self.check_id = check_id
        self.message = message
        self.public_reason = PUBLIC_REASONS.get(check_id, "검증 실패")
