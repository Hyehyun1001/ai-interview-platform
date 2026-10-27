"""실제 모델 통합 스모크 (기본 건너뜀). 실행: RUN_REAL_MODELS=1 .venv/bin/python -m pytest tests/test_real_models.py -s

필요: macOS(`say`), faster-whisper 모델 캐시, `ollama serve` + qwen2.5:7b-instruct-q4_K_M. 가짜 엔진으로는 증명할 수 없는
"실제 어댑터가 실제 모델과 맞물리는가"를 확인한다. 합성음 기준이므로 실제 지원자 음성의 정확도를 대신하지 않는다.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.ai.chains.followup_chain import generate_followup_streaming
from app.ai.chains.prompts import FollowupInputs
from app.ai.guardrail import GroundingContext, ListSink
from app.ai.llm import llm_factory
from app.ai.stt.faster_whisper_engine import FasterWhisperSTT
from app.ai.tts.local_say import LocalSayTTS
from app.interview.incremental_stt import IncrementalStt
from app.interview.vad import EnergyVad
from tests.conftest import make_settings

pytestmark = pytest.mark.skipif(os.environ.get("RUN_REAL_MODELS") != "1", reason="RUN_REAL_MODELS=1 일 때만 실행")
REPO = Path(__file__).resolve().parents[2]
AUDIO = REPO / "data" / "benchmarks" / "audio" / "answer_60s_synth.wav"


def _cer(ref: str, hyp: str) -> float:
    from tests.benchmark_ai import cer

    return cer(ref, hyp)


def _pcm60() -> tuple[bytes, str]:
    import wave

    from tests.benchmark_ai import ANSWER_60S, synth_wav

    if not AUDIO.exists():
        synth_wav(ANSWER_60S, AUDIO, "Yuna")
    with wave.open(str(AUDIO), "rb") as w:
        return w.readframes(w.getnframes()), ANSWER_60S


async def test_local_say_tts_produces_valid_wav():
    chunks = [c async for c in LocalSayTTS("Yuna").synthesize("캐시 무효화는 어떻게 처리하셨나요?")]
    data = b"".join(chunks)
    assert data[:4] == b"RIFF" and data[8:12] == b"WAVE" and len(data) > 10_000 and len(chunks) >= 1
    print(f"\n[TTS] {len(data)} bytes in {len(chunks)} chunks")


async def test_faster_whisper_adapter_and_incremental_stt_on_real_audio():
    pcm, ref = _pcm60()
    stt = FasterWhisperSTT(cpu_threads=6)
    t0 = time.perf_counter()
    full = await stt.transcribe_pcm(pcm)
    print(f"\n[STT full 60s] {time.perf_counter() - t0:.1f}s CER={_cer(ref, full.text):.3f} lowconf={full.low_confidence}")
    assert _cer(ref, full.text) < 0.15 and not full.low_confidence

    inc = IncrementalStt(stt)  # 운영 기본값(최소 8s, 최대 25s, 침묵 0.4s)
    vad, fed = EnergyVad(), 0
    for i in range(0, len(pcm), 16000):  # 500ms 청크
        chunk = pcm[i:i + 16000]
        vad.feed(chunk)
        inc.feed(chunk, vad)
        fed += len(chunk)
    chunks_before_end = inc.chunks_dispatched
    t1 = time.perf_counter()
    res = await inc.finish()
    print(f"[STT incremental] dispatched_before_end={chunks_before_end} total_chunks={inc.chunks_dispatched} "
          f"finish_wait={time.perf_counter() - t1:.1f}s CER={_cer(ref, res.text):.3f}")
    assert chunks_before_end >= 1  # 답변이 끝나기 전에 이미 확정 구간 디코딩이 시작되었다
    assert _cer(ref, res.text) < 0.25  # 구간 경계에서 약간의 품질 저하는 허용


async def test_real_qwen_streams_followup_in_decided_key_order_and_passes_guardrail():
    settings = make_settings(Path("/tmp/unused.db"))
    answer = "Redis로 캐시를 붙여서 속도를 올렸어요. 그냥 TTL로 해결했고요, 크게 문제는 없었습니다."
    resume = '{"name":"김지원","projects":[{"title":"주문 조회 성능 개선","tech_stack":["Spring Boot","Redis","MySQL"]}]}'
    inputs = FollowupInputs("캐시를 도입한 효과를 설명해 주세요.", answer, "turn:1", resume, {}, ["자기소개를 해주세요."], 0, 2,
                            {"trigger_ambiguous": True, "trigger_contradiction": True, "trigger_stt_unclear": True})
    ctx = GroundingContext(answer_text=answer, resume_text=resume, asked_questions=["자기소개를 해주세요."], sources={"turn:1": answer})
    marks: dict[str, float] = {}
    t0 = time.perf_counter()

    async def on_ready(partial):  # noqa: ANN001, ANN202
        marks["tts_start"] = time.perf_counter() - t0
        marks["question"] = partial.question

    sink = ListSink()
    res = await generate_followup_streaming(llm_factory(settings), inputs, ctx, on_question_ready=on_ready, sink=sink, timeout_s=30)
    total = time.perf_counter() - t0
    d = res.value.decision
    print(f"\n[Qwen] attempts={res.attempts} fell_back={res.fell_back} needed={d.needed} spoken_early={res.value.spoken_early} "
          f"tts_start={marks.get('tts_start', float('nan')):.2f}s total={total:.2f}s")
    print(f"       question={d.question!r} keywords={d.grounding_keywords} events={[(e.check_id, e.outcome) for e in sink.events]}")
    assert res.value.decision.needed is False or (res.value.decision.question and res.value.decision.grounding_keywords)
    if d.needed and not res.fell_back:
        assert res.value.spoken_early and marks["tts_start"] < total  # 질문이 JSON 전체 완성보다 먼저 TTS 로 넘어갔다
        for kw in d.grounding_keywords:  # 환각 방지: 모든 키워드가 답변/이력서에 실재
            assert kw.lower().rstrip("로를은는이가") in (answer + resume).lower() or kw in (answer + resume)
