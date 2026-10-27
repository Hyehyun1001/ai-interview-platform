"""운영 기본 엔진 조립 (M0 확정: faster-whisper turbo / macOS say / Ollama Qwen2.5). 테스트는 create_app(engines=...) 로 대체한다."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.guardrail import DbGuardrailEventSink
from app.ai.llm import llm_factory
from app.ai.stt.faster_whisper_engine import FasterWhisperSTT
from app.ai.tts.local_say import LocalSayTTS
from app.core.config import Settings
from app.interview.brain import ChainBrain
from app.interview.media_store import MediaStore
from app.interview.runtime import Engines, Tuning


def build_default_engines(settings: Settings, sessionmaker: async_sessionmaker) -> Engines:
    sink = DbGuardrailEventSink(sessionmaker)
    return Engines(
        stt=FasterWhisperSTT(settings.stt_model, settings.stt_compute_type, settings.stt_cpu_threads),
        tts=LocalSayTTS(settings.tts_voice),  # tts_provider=edge(외부 전송)는 opt-in 이며 아직 구현하지 않는다 (TRD §0 T-2)
        brain=ChainBrain(sessionmaker, llm_factory(settings), sink=sink, timeout_s=settings.llm_timeout_s),
        media=MediaStore(settings.media_root), sink=sink, tuning=Tuning())
