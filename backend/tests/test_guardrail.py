"""Guardrail G2~G6 개별 검증과 조합 (TRD §3.5)."""
from __future__ import annotations

import pytest

from app.ai.errors import GuardrailError
from app.ai.guardrail import (GroundingContext, approx_substring_distance, check_duplicate, check_evidence, check_forbidden,
                              check_form, check_keyword_grounding, jaccard, normalize_compact, strip_josa, verify_all,
                              verify_before_tts, verify_evidence)
from app.schemas.ai import Evidence, FollowupDecision, MainQuestion

ANSWER = "Redis로 캐시를 붙여서 속도를 올렸어요. 그냥 TTL로 해결했고요."
RESUME = '{"name":"김지원","projects":[{"title":"주문 조회 성능 개선","tech_stack":["Spring Boot","Redis"]}]}'


def ctx(**kw) -> GroundingContext:
    base = dict(answer_text=ANSWER, resume_text=RESUME, asked_questions=["자기소개를 해주세요."],
                sources={"turn:1": ANSWER, "chunk:1": "주문 조회 성능 개선 프로젝트에서 Redis 캐시를 도입했습니다."})
    return GroundingContext(**{**base, **kw})


def followup(question="Redis 캐시 무효화는 어떻게 처리하셨나요?", keywords=("Redis", "캐시"), evidence=()) -> FollowupDecision:
    return FollowupDecision(needed=True, reason="ambiguous", grounding_keywords=list(keywords), question=question,
                            evidence=list(evidence))


def fails(check_id: str, fn, *args) -> GuardrailError:
    with pytest.raises(GuardrailError) as e:
        fn(*args)
    assert e.value.check_id == check_id
    return e.value


# ── 정규화 / 조사 ────────────────────────────────────────────────────────────
def test_normalize_and_josa():
    assert normalize_compact("Redis로  캐시를, 붙여서!") == "redis로캐시를붙여서"
    assert strip_josa("캐시를") == "캐시" and strip_josa("서버에서는") == "서버" and strip_josa("데이터") == "데이터"
    assert strip_josa("redis로") == "redis"


# ── G2 키워드 Grounding ──────────────────────────────────────────────────────
def test_g2_passes_when_keywords_appear_in_answer_or_resume():
    check_keyword_grounding(["Redis", "캐시", "TTL"], ctx())
    check_keyword_grounding(["Spring Boot"], ctx())  # 이력서에만 있어도 허용 (모순 대조용)


def test_g2_strips_josa_from_keyword():
    check_keyword_grounding(["캐시를", "TTL로"], ctx())


def test_g2_rejects_missing_keyword_and_does_not_leak_into_public_reason():
    err = fails("G2", check_keyword_grounding, ["Redis", "Kafka"], ctx())
    assert "Kafka" in err.message  # 재시도 프롬프트에는 구체 사유
    assert "Kafka" not in err.public_reason  # DB 로그용 문구에는 사용자 텍스트가 없다


@pytest.mark.parametrize("kws", [[], ["가"], [" "]])
def test_g2_rejects_empty_or_too_short(kws):
    fails("G2", check_keyword_grounding, kws, ctx())


def test_g2_is_case_and_space_insensitive():
    check_keyword_grounding(["redis"], ctx())
    check_keyword_grounding(["spring boot"], ctx(resume_text="Spring  Boot 경험"))


# ── G3 Evidence quote ────────────────────────────────────────────────────────
def test_g3_exact_and_whitespace_variant_quote_passes():
    ev = [Evidence(source="answer", ref="turn:1", quote="Redis로 캐시를 붙여서 속도를 올렸어요"),
          Evidence(source="resume", ref="chunk:1", quote="Redis  캐시를 도입했습니다")]
    check_evidence(ev, ctx())


def test_g3_allows_small_edit_distance_up_to_15_percent():
    # 20자 인용에서 3자 이하 차이 = 15% → 허용 (STT/표기 변이 흡수)
    check_evidence([Evidence(source="answer", ref="turn:1", quote="Redis로 캐시를 붙여서 속도를 올렸어")], ctx())  # 마지막 글자 누락
    check_evidence([Evidence(source="answer", ref="turn:1", quote="Redis로 캐쉬를 붙여서 속도를 올렸어요")], ctx())  # 1글자 치환


def test_g3_rejects_fabricated_quote_unknown_ref_and_empty_quote():
    fails("G3", check_evidence, [Evidence(source="answer", ref="turn:1", quote="Kafka로 이벤트를 비동기 처리했습니다")], ctx())
    fails("G3", check_evidence, [Evidence(source="answer", ref="turn:99", quote="Kafka 로 비동기 처리했습니다")], ctx())
    fails("G3", check_evidence, [Evidence(source="answer", ref="turn:1", quote="  ")], ctx())


def test_approx_substring_distance():
    assert approx_substring_distance("abc", "xxabcxx") == 0
    assert approx_substring_distance("abc", "xxaxcxx") == 1
    assert approx_substring_distance("", "abc") == 0


# ── G4 금칙어 / 인적 속성 ────────────────────────────────────────────────────
@pytest.mark.parametrize("q", [
    "결혼 계획이 있으신가요?", "나이가 어떻게 되시나요?", "고향이 어디세요?", "종교가 있으신가요?", "부모님은 무슨 일을 하세요?",
    "자녀가 있으신가요?", "성별이 어떻게 되시나요?", "출산 계획이 있으신가요?", "혈액형이 뭐예요?"])
def test_g4_blocks_personal_attribute_questions(q):
    fails("G4", check_forbidden, q)


@pytest.mark.parametrize("q", [
    "나이브 베이즈 분류기를 선택한 이유는 무엇인가요?",  # '나이브' 오탐 방지
    "장애 대응 경험을 말씀해 주세요.",  # IT 용어 '장애'
    "Redis 키 설계는 어떻게 하셨나요?", "여성 고객 대상 서비스에서 개인화는 어떻게 구현하셨나요?",
    "아이디어를 구체화한 과정을 설명해 주세요."])
def test_g4_does_not_flag_legitimate_it_questions(q):
    check_forbidden(q)


# ── G5 중복 ──────────────────────────────────────────────────────────────────
def test_g5_blocks_near_duplicate_and_allows_different_question():
    asked = ["Redis 캐시 무효화는 어떻게 처리하셨나요?"]
    fails("G5", check_duplicate, "Redis 캐시 무효화는 어떻게 처리했나요?", asked)
    fails("G5", check_duplicate, "Redis 캐시 무효화는 어떻게 처리하셨나요?", asked)  # 완전 동일
    check_duplicate("Kafka 파티션 키는 어떻게 정하셨나요?", asked)
    check_duplicate("무엇이든", [])


def test_jaccard_bounds():
    assert jaccard("", "") == 0.0 and jaccard("abcdef", "abcdef") == 1.0 and 0 < jaccard("abcdef", "abcxyz") < 1


# ── G6 길이 / 형식 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("q", ["캐시 무효화는 어떻게 처리하셨나요?", "그 선택의 이유를 설명해 주세요.", "왜 TTL 만 사용하셨어요?",
                               "이 설계가 맞는 이유는 무엇입니까", "Redis 를 쓴 이유가 있나요"])
def test_g6_accepts_question_and_polite_request_forms(q):
    check_form(q)


@pytest.mark.parametrize("q,why", [
    ("", "빈 질문"), ("x" * 121 + "요?", "120자 초과"),
    ("Redis 를 쓰셨군요. 왜 쓰셨나요?", "두 문장"), ("캐시를 적용했습니다.", "평서문"),
    ("첫째 줄\n둘째 줄이 있나요?", "개행"), ("   ", "공백")])
def test_g6_rejects_bad_form(q, why):
    fails("G6", check_form, q)


def test_g6_allows_decimal_numbers_inside_one_sentence():
    check_form("응답 시간을 3.5초에서 0.8초로 줄인 방법은 무엇인가요?")


# ── 조합 ─────────────────────────────────────────────────────────────────────
def test_verify_before_tts_skips_g3_but_verify_all_runs_it():
    bad_evidence = [Evidence(source="answer", ref="turn:1", quote="전혀 없던 문장입니다 정말로요")]
    d = followup(evidence=bad_evidence)
    verify_before_tts(d, ctx())  # TTS 시작 전에는 G3 를 보지 않는다
    fails("G3", verify_evidence, d, ctx())
    fails("G3", verify_all, d, ctx())


def test_verify_before_tts_order_g2_before_g4():
    d = followup(question="결혼 계획이 있으신가요?", keywords=("Kafka",))
    fails("G2", verify_before_tts, d, ctx())  # 키워드 근거 실패가 먼저 보고된다


def test_verify_skips_everything_when_followup_not_needed():
    skip = FollowupDecision.skip()
    verify_before_tts(skip, ctx())
    verify_all(skip, ctx())


def test_verify_all_main_question_uses_g3_g4_g5_g6_without_g2():
    ok = MainQuestion(question="주문 조회 성능을 어떻게 개선하셨나요?", category="기술", evidence=[])
    verify_all(ok, ctx())
    fails("G5", verify_all, MainQuestion(question="자기소개를 해주세요.", category="인성", evidence=[]), ctx())
    fails("G4", verify_all, MainQuestion(question="결혼은 하셨나요?", category="인성", evidence=[]), ctx())


# ── G3: 잘못된 ref/source 라벨은 바로잡되, 인용문이 근거에 없으면 여전히 실패 ─────────────────
def test_evidence_with_wrong_ref_label_is_resolved_by_quote_but_hallucinated_quote_still_fails():
    from app.ai.errors import GuardrailError
    from app.ai.guardrail import GroundingContext, check_evidence
    from app.schemas.ai import Evidence

    ctx = GroundingContext(sources={"chunk-1": "Redis 캐시 도입으로 조회 응답 시간을 800ms 에서 200ms 로 개선", "turn:7": "캐시 무효화는 키를 삭제했습니다"})
    ok = Evidence(source="project", ref="주문 조회 성능 개선", quote="Redis 캐시 도입으로 조회 응답 시간을 800ms에서 200ms로 개선")  # type: ignore[arg-type]
    check_evidence([ok], ctx)
    assert ok.source == "resume" and ok.ref == "chunk-1"  # 라벨 정정
    other = Evidence(source="answer", ref="이상한 ref", quote="캐시 무효화는 키를 삭제했습니다")
    check_evidence([other], ctx)
    assert other.ref == "turn:7"
    for bad in (Evidence(source="resume", ref="chunk-1", quote="Kafka 로 이벤트를 처리했습니다"), Evidence(source="resume", ref="없는 ref", quote="Kafka 로 이벤트를 처리했습니다")):
        try:
            check_evidence([bad], ctx)
        except GuardrailError as e:
            assert e.check_id == "G3"
        else:
            raise AssertionError("환각 인용이 통과했다")
    # ref 가 맞아도 그 원문에 인용이 없으면 실패 (다른 원문에 있어도 ref 를 속일 수 없다)
    try:
        check_evidence([Evidence(source="resume", ref="chunk-1", quote="캐시 무효화는 키를 삭제했습니다")], ctx)
    except GuardrailError as e:
        assert e.check_id == "G3"
    else:
        raise AssertionError("ref 와 불일치하는 인용이 통과했다")
