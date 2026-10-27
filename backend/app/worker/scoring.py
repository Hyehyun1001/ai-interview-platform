"""리포트 점수 산출 (TRD §6.3) — LLM 과 DB 에 의존하지 않는 순수 함수. 단위 테스트로 산식을 고정한다."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

LEVEL_TO_SCORE = 20  # 루브릭 1~5 → 20~100
GAZE_PENALTY_CAP = 5.0
CRITERIA = ("concept_understanding", "logic", "delivery", "attitude", "job_expertise", "code_quality")


def level_score(level: int) -> float:
    return float(level * LEVEL_TO_SCORE)


def criterion_means(turn_levels: Sequence[Mapping[str, int]]) -> dict[str, float]:
    """criterion_score(c) = mean(turn-level score of c). 채점된 턴이 없는 항목은 결과에 넣지 않는다."""
    out: dict[str, float] = {}
    for c in CRITERIA:
        vals = [level_score(t[c]) for t in turn_levels if c in t]
        if vals:
            out[c] = sum(vals) / len(vals)
    return out


def effective_weights(weights: Mapping[str, int], available: Sequence[str]) -> dict[str, float]:
    """점수가 없는 항목(예: 코딩테스트 OFF 인데 code_quality 가중치가 남아 있는 경우)을 빼고 나머지 합이 100 이 되게 재정규화한다."""
    used = {c: weights.get(c, 0) for c in available if weights.get(c, 0) > 0}
    total = sum(used.values())
    if total:
        return {c: w * 100.0 / total for c, w in used.items()}
    # 채점된 항목의 가중치가 모두 0 이면(설정 오류) 동일 가중치로 계산한다 — 점수를 아예 못 내는 것보다 낫고, weights_snapshot 에 그대로 남는다
    return {c: 100.0 / len(available) for c in available} if available else {}


def gaze_penalty(ratio: float | None, enabled: bool) -> float:
    """가중치 설정에서 gaze_penalty_enabled 인 경우에만 min(5, ratio × 20)."""
    if not enabled or ratio is None:
        return 0.0
    return min(GAZE_PENALTY_CAP, max(0.0, ratio) * 20.0)


def total_score(means: Mapping[str, float], weights: Mapping[str, int], penalty: float = 0.0) -> tuple[float | None, dict[str, float]]:
    """total = Σ(weight_c × score_c)/100 − gaze 감점. 채점된 항목이 없으면 (None, {})."""
    eff = effective_weights(weights, list(means))
    if not eff:
        return None, {}
    raw = sum(eff[c] * means[c] for c in eff) / 100.0
    return round(min(100.0, max(0.0, raw - penalty)), 2), eff


def merge_intervals(intervals: Sequence[tuple[int, int]], clip_end: int) -> list[tuple[int, int]]:
    """겹치는 시선 이벤트(종류가 달라도)를 합치고 답변 길이로 자른다 — 같은 시간을 두 번 세지 않기 위해."""
    clipped = sorted((max(0, s), min(e, clip_end)) for s, e in intervals if min(e, clip_end) > max(0, s))
    merged: list[list[int]] = []
    for s, e in clipped:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def gaze_away_ratio(turns: Sequence[tuple[int, Sequence[tuple[int, int]]]]) -> float | None:
    """Σ(이벤트 지속시간) / Σ(답변 시간). turns: [(답변 길이 ms, [(start_ms, end_ms)…])]. 답변 시간이 0 이면 None."""
    total = sum(d for d, _ in turns if d > 0)
    if total <= 0:
        return None
    away = sum(e - s for d, ev in turns if d > 0 for s, e in merge_intervals(ev, d))
    return round(min(1.0, away / total), 4)


def predict(total: float | None, cutoff: float | None, margin: float) -> str:
    """TRD §6.3: cutoff 미설정 → unavailable, ≥ cutoff+margin → likely_pass, ≥ cutoff−margin → borderline, 그 외 unlikely."""
    if total is None or cutoff is None:
        return "unavailable"
    if total >= cutoff + margin:
        return "likely_pass"
    if total >= cutoff - margin:
        return "borderline"
    return "unlikely"


def quote_span_ms(answer: str, quote: str, duration_ms: int) -> tuple[int, int] | None:
    """인용 구간의 오디오 상 위치 추정. STT 가 단어 시간을 저장하지 않으므로 글자 위치를 답변 길이에 **비례 배분**한 근사치다.
    공백 차이를 흡수하기 위해 공백을 제거한 문자열에서 찾는다. 찾지 못하면 None."""
    if duration_ms <= 0 or not answer or not quote:
        return None
    flat = "".join(answer.split())
    q = "".join(quote.split())
    i = flat.find(q)
    if i < 0 or not flat:
        return None
    start = int(duration_ms * i / len(flat))
    end = int(duration_ms * (i + len(q)) / len(flat))
    return start, max(start + 1, min(end, duration_ms))


@dataclass
class RankedItem:
    title: str
    detail: str


def fallback_narrative(means: Mapping[str, float], labels: Mapping[str, str], total: float | None) -> tuple[str, list[RankedItem], list[RankedItem]]:
    """LLM 총평이 3회 검증에 실패했을 때의 결정적 대체: 점수 순위로만 강점/개선점을 고른다. 근거 인용 없이 점수 사실만 말한다."""
    ranked = sorted(means.items(), key=lambda kv: kv[1], reverse=True)
    top = ranked[:3]
    low = [kv for kv in reversed(ranked)][:3]
    head = f"종합 점수는 {total:.1f}점입니다. " if total is not None else ""
    best, worst = labels[top[0][0]], labels[low[0][0]]
    summary = f"{head}{best} 항목이 가장 높고 {worst} 항목이 가장 낮았습니다. (자동 요약이 불가해 점수 기반으로 작성되었습니다.)"
    strengths = [RankedItem(f"{labels[c]} 우수", f"{labels[c]} 항목 {s:.0f}점으로 상대적으로 높습니다.") for c, s in top]
    improvements = [RankedItem(f"{labels[c]} 보완", f"{labels[c]} 항목 {s:.0f}점으로 상대적으로 낮습니다.") for c, s in low]
    return summary, strengths, improvements
