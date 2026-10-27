"""리포트 점수 산식 (TRD §6.3) — 순수 함수."""
from __future__ import annotations

import pytest

from app.worker import scoring as sc

W = {"concept_understanding": 25, "logic": 20, "delivery": 15, "attitude": 10, "job_expertise": 30, "code_quality": 0}


def test_level_to_score_and_means_skip_missing_criteria():
    assert [sc.level_score(x) for x in (1, 3, 5)] == [20.0, 60.0, 100.0]
    means = sc.criterion_means([{"logic": 5, "delivery": 1}, {"logic": 3}])
    assert means == {"logic": 80.0, "delivery": 20.0}  # logic=(100+60)/2, delivery 는 채점된 턴만
    assert sc.criterion_means([]) == {}


def test_total_is_weighted_sum_and_renormalizes_when_a_criterion_has_no_score():
    means = {"concept_understanding": 80.0, "logic": 60.0, "delivery": 100.0, "attitude": 40.0, "job_expertise": 70.0}
    total, eff = sc.total_score(means, W)
    assert total == pytest.approx((25 * 80 + 20 * 60 + 15 * 100 + 10 * 40 + 30 * 70) / 100, abs=0.01)
    assert sum(eff.values()) == pytest.approx(100) and "code_quality" not in eff
    # code_quality 가중치가 남아 있어도 점수가 없으면 나머지로 재정규화
    total2, eff2 = sc.total_score(means, {**W, "code_quality": 20, "job_expertise": 10})
    assert "code_quality" not in eff2 and sum(eff2.values()) == pytest.approx(100)
    # 일부 항목만 채점된 경우
    t3, e3 = sc.total_score({"logic": 80.0, "delivery": 40.0}, W)
    assert e3 == {"logic": pytest.approx(20 / 35 * 100), "delivery": pytest.approx(15 / 35 * 100)}
    assert t3 == pytest.approx((20 * 80 + 15 * 40) / 35, abs=0.01)  # 저장값은 소수 둘째 자리


def test_total_edge_cases():
    assert sc.total_score({}, W) == (None, {})
    t, eff = sc.total_score({"logic": 50.0, "delivery": 70.0}, {c: 0 for c in W})  # 설정 오류: 모든 가중치 0 → 동일 가중치
    assert t == 60.0 and eff == {"logic": 50.0, "delivery": 50.0}
    assert sc.total_score({"logic": 100.0}, W, penalty=5)[0] == 95.0
    assert sc.total_score({"logic": 10.0}, W, penalty=5)[0] == 5.0
    assert sc.total_score({"logic": 3.0}, W, penalty=5)[0] == 0.0  # 하한 0


def test_gaze_penalty_only_when_enabled_and_capped_at_5():
    assert sc.gaze_penalty(0.1, False) == 0.0 and sc.gaze_penalty(None, True) == 0.0
    assert sc.gaze_penalty(0.1, True) == pytest.approx(2.0)
    assert sc.gaze_penalty(0.9, True) == 5.0 and sc.gaze_penalty(-1, True) == 0.0


def test_merge_intervals_does_not_double_count_overlaps_and_clips_to_answer():
    assert sc.merge_intervals([(0, 1000), (500, 1500), (3000, 3500)], 10_000) == [(0, 1500), (3000, 3500)]
    assert sc.merge_intervals([(9000, 12_000), (-100, 200)], 10_000) == [(0, 200), (9000, 10_000)]
    assert sc.merge_intervals([(500, 500), (700, 600)], 10_000) == []


def test_gaze_ratio_is_sum_of_event_time_over_sum_of_answer_time():
    # 턴1: 10s 중 2s(겹침 합산 후), 턴2: 30s 중 1s → 3/40
    assert sc.gaze_away_ratio([(10_000, [(0, 1500), (1000, 2000)]), (30_000, [(5000, 6000)])]) == pytest.approx(0.075)
    assert sc.gaze_away_ratio([(0, [(0, 100)])]) is None and sc.gaze_away_ratio([]) is None
    assert sc.gaze_away_ratio([(1000, [(0, 5000)])]) == 1.0  # 1 을 넘지 않는다


@pytest.mark.parametrize("total,expected", [
    (85.0, "likely_pass"), (80.0, "likely_pass"),   # cutoff 70 + margin 10 포함
    (79.99, "borderline"), (60.0, "borderline"),    # cutoff − margin 포함
    (59.99, "unlikely"), (0.0, "unlikely")])
def test_prediction_boundaries(total, expected):
    assert sc.predict(total, 70.0, 10.0) == expected


def test_prediction_unavailable_without_cutoff_or_score():
    assert sc.predict(90.0, None, 5.0) == "unavailable" and sc.predict(None, 70.0, 5.0) == "unavailable"


def test_quote_span_is_proportional_to_text_position_and_whitespace_insensitive():
    answer = "가나다라마 바사아자차 카타파하하"  # 공백 제외 15자
    s, e = sc.quote_span_ms(answer, "바사아자차", 15_000)  # 5~10번째 글자
    assert (s, e) == (5000, 10_000)
    assert sc.quote_span_ms(answer, "바 사 아", 15_000) == (5000, 8000)
    assert sc.quote_span_ms(answer, "없는문장", 15_000) is None
    assert sc.quote_span_ms(answer, "가나", 0) is None and sc.quote_span_ms("", "x", 100) is None
    s2, e2 = sc.quote_span_ms("ab", "b", 1)
    assert e2 > s2  # CHECK(end_ms >= start_ms) 를 항상 만족


def test_fallback_narrative_is_deterministic_and_score_only():
    labels = {"logic": "논리성", "delivery": "전달력", "attitude": "태도"}
    summary, strengths, improvements = sc.fallback_narrative({"logic": 90.0, "delivery": 40.0, "attitude": 60.0}, labels, 63.3)
    assert "63.3" in summary and "논리성" in summary and "전달력" in summary
    assert strengths[0].title.startswith("논리성") and improvements[0].title.startswith("전달력")
    assert len(strengths) == 3 and len(improvements) == 3
