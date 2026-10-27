"""면접 세션 런타임: 질문 → TTS → 카운트다운 → 답변 → STT → 꼬리질문 판단 → 다음 질문 (TRD §4.2, §7.7, 흐름도 AI_Interview_Loop).

* 서버가 상태의 단일 진실 원천이다. 클라이언트는 tts_done / answer_start / answer_end / text_answer / gaze_event 만 보낸다.
* 모든 턴·답변은 즉시 DB/디스크에 기록한다 (NFR-Q2). 연결이 끊겨도 세션은 `paused` 로 유지되고 재접속 시 현재 상태를 재전송한다.
* 질문 N+1 사전 생성(prefetch), 백그라운드 청크 증분 STT, 꼬리질문 `question` 스트리밍 TTS (TRD §2.4 지연 최적화)를 사용한다.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.errors import LLMUnavailable
from app.ai.guardrail import GuardrailEventSink
from app.ai.stt.base import STTEngine, SttResult
from app.ai.tts.base import TTSEngine
from app.interview.brain import FollowupContext, InterviewBrain, QuestionDraft, SessionConfig
from app.interview.incremental_stt import IncrementalStt
from app.interview.media_store import AnswerRecording, MediaStore
from app.interview.vad import EnergyVad
from app.models import Application, GazeEvent, InterviewSession, InterviewTurn
from app.models.enums import AnswerEndReason, ApplicationStatus, FollowupReason, GazeKind, SessionState, TurnKind
from app.schemas.ai import FollowupDecision
from app.schemas.ws import (CLIENT_ADAPTER, AnswerEnd, AnswerStart, GazeEventMsg, Ping, Pong, ResumeMsg, TextAnswer, TtsDone,
                            server_message)

log = logging.getLogger("app.interview")

GAZE_MESSAGES = {
    GazeKind.GAZE_AWAY: "화면 밖을 응시하고 있어요. 화면을 바라봐 주세요.",  # 부정행위 단정 표현 금지 (TRD §4.4)
    GazeKind.FACE_LOST: "얼굴이 보이지 않아요. 카메라 앞에서 진행해 주세요.",
    GazeKind.MULTI_FACE: "화면에 여러 사람이 보여요. 혼자 응시해 주세요.",
}


class Phase(str, Enum):
    IDLE = "idle"  # 첫 질문 전
    ASKING = "asking"  # 질문 출력(TTS) 중 / 재접속 대기
    COUNTDOWN = "countdown"
    AWAITING_START = "awaiting_start"  # 카운트다운 끝, answer_start 대기
    ANSWERING = "answering"
    THINKING = "thinking"  # STT · 분석 · 생성
    CODING = "coding"
    FINISHED = "finished"


@dataclass
class Tuning:
    """타이밍·임계값. 운영 기본값은 TRD 값이며 테스트에서만 줄인다."""

    countdown_step_s: float = 1.0
    tts_done_timeout_s: float = 120.0
    tts_fail_grace_s: float = 5.0  # TTS 실패(자막만) 시 자동 카운트다운까지 (UI_SPEC §4.6.6)
    answer_start_grace_s: float = 5.0
    reconnect_grace_s: float = 30.0  # 답변 중 연결이 끊긴 뒤 자동 종료까지
    pause_ttl_s: float = 1800.0  # paused 유지 30분 (TRD §4.5)
    silence_end_ms: int = 2000  # 연속 침묵 종료 (TRD §4.2)
    min_answer_ms: int = 1000  # 이보다 짧으면 "다시 말씀해 주세요"
    max_reasks: int = 2
    gaze_warning_limit: int = 3  # 세션당 최대 경고 (TRD §4.4)
    timeout_scale: float = 1.0  # 답변 제한시간 배율 (테스트용)
    ping_interval_s: float = 15.0  # 제어 채널 ping 주기 (TRD §7.7)
    vad_rms: float = 400.0
    initial_prompt: str | None = None
    countdown_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep  # 카운트다운 간격 전용 (테스트에서만 주입)


@dataclass
class Engines:
    stt: STTEngine
    tts: TTSEngine
    brain: InterviewBrain
    media: MediaStore
    sink: GuardrailEventSink | None = None
    tuning: Tuning = field(default_factory=Tuning)


@dataclass
class TurnState:
    turn_id: uuid.UUID
    turn_no: int
    kind: TurnKind
    main_index: int
    text: str
    time_limit_sec: int
    category: str | None = None
    parent_turn_id: uuid.UUID | None = None
    reasks: int = 0
    recording: AnswerRecording | None = None
    vad: EnergyVad | None = None
    inc: IncrementalStt | None = None
    started_mono: float | None = None
    text_mode: bool = False  # 코드 꼬리질문: TTS·카운트다운 없이 텍스트 답변


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SessionRuntime:
    def __init__(self, session_id: uuid.UUID, user_id: uuid.UUID, sessionmaker: async_sessionmaker, eng: Engines,
                 on_release: Callable[[uuid.UUID], None] | None = None):
        self.session_id, self.user_id, self.sm, self.eng = session_id, user_id, sessionmaker, eng
        self.on_release = on_release
        self.cfg: SessionConfig | None = None
        self.ws: WebSocket | None = None
        self.phase = Phase.IDLE
        self.turn: TurnState | None = None
        self.turn_no_counter = 0
        self.main_asked = 0
        self.followup_count = 0
        self.asked: list[str] = []
        self.gaze_warnings = 0
        self.degraded = False
        self._seq = 0
        self._last_client_seq = -1
        self._stage = "stt"
        self._lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._tts_done = asyncio.Event()
        self._answer_start = asyncio.Event()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._prefetch: tuple[int, asyncio.Task[QuestionDraft]] | None = None
        self._recovered: tuple[TurnState, str] | None = None
        self.closed = False
        self.media_frames_dropped = 0

    # ── 로드 / 복원 ────────────────────────────────────────────────────────────
    async def load(self) -> None:
        self.cfg = await self.eng.brain.load_config(self.session_id)
        async with self.sm() as db:
            sess = await db.get(InterviewSession, self.session_id)
            self.followup_count, self.degraded = sess.followup_count, sess.degraded_mode
            turns = (await db.execute(select(InterviewTurn).where(InterviewTurn.session_id == self.session_id)
                                      .order_by(InterviewTurn.turn_no))).scalars().all()
        self.asked = [t.question_text for t in turns]
        self.turn_no_counter = turns[-1].turn_no if turns else 0
        self.main_asked = sum(1 for t in turns if t.kind == TurnKind.MAIN)
        if turns:
            last = turns[-1]
            ts = TurnState(last.id, last.turn_no, last.kind, last.main_index or 0, last.question_text,
                           self.cfg.answer_limit_sec, last.question_category, last.parent_turn_id,
                           text_mode=last.kind == TurnKind.CODE_FOLLOWUP)
            if last.answer_ended_at is None:
                self.turn, self.phase = ts, Phase.ASKING  # 답변 전 → 재접속 시 질문을 다시 낭독하고 처음부터 재개 (UI_SPEC §4.6.6)
            elif last.answer_text is not None:
                self.turn, self.phase = ts, Phase.THINKING  # 답변은 저장됐으나 다음 질문 전에 중단 → 이어서 진행
                self._recovered = (ts, last.answer_text)
        if sess.state == SessionState.CODING:
            self.phase = Phase.CODING
        elif sess.state == SessionState.FINISHED:
            self.phase = Phase.FINISHED

    # ── 송신 ──────────────────────────────────────────────────────────────────
    async def send(self, msg_type: str, **payload: Any) -> bool:
        """제어 채널 송신. 연결 단절은 False 로 알리고 세션은 유지한다(재접속 시 복구). 그 외 예외는 프로그래밍 오류이므로 전파한다."""
        async with self._send_lock:
            ws = self.ws
            if ws is None:
                return False
            self._seq += 1
            message = server_message(msg_type, self._seq, **payload)  # 봉투 키 충돌 등 오류는 여기서 즉시 드러난다
            try:
                await ws.send_json(message)
                return True
            except (WebSocketDisconnect, RuntimeError, ConnectionError) as e:  # 끊김/이미 닫힘
                log.info("send failed type=%s err=%s", msg_type, type(e).__name__)
                if self.ws is ws:
                    self.ws = None
                return False

    async def error(self, code: str, message: str, *, recoverable: bool = True) -> None:
        await self.send("error", code=code, recoverable=recoverable, message=message)

    # ── 태스크 관리 ───────────────────────────────────────────────────────────
    def _spawn(self, name: str, coro: Coroutine[Any, Any, Any]) -> None:
        self._cancel(name)

        async def runner() -> None:
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001  백그라운드 오류가 조용히 사라지지 않게 한다 (원문·PII 는 로그에 남기지 않음)
                log.error("task %s failed: %s", name, type(e).__name__)
                await self.error("INTERNAL", "일시적인 오류가 발생했습니다", recoverable=False)

        self._tasks[name] = asyncio.create_task(runner(), name=f"{self.session_id}:{name}")

    def _cancel(self, name: str) -> None:
        t = self._tasks.pop(name, None)
        if t and not t.done() and t is not asyncio.current_task():
            t.cancel()

    # ── DB 헬퍼 ───────────────────────────────────────────────────────────────
    async def _update_session(self, **fields: Any) -> None:
        async with self.sm() as db:
            sess = await db.get(InterviewSession, self.session_id)
            for k, v in fields.items():
                setattr(sess, k, v)
            await db.commit()

    async def _mark_application_interviewing(self) -> None:
        async with self.sm() as db:
            sess = await db.get(InterviewSession, self.session_id)
            app = await db.get(Application, sess.application_id)
            if app is not None and app.status in (ApplicationStatus.APPLIED, ApplicationStatus.PREPARED):
                app.status = ApplicationStatus.INTERVIEWING
                await db.commit()

    async def _update_turn(self, turn_id: uuid.UUID, **fields: Any) -> None:
        async with self.sm() as db:
            row = await db.get(InterviewTurn, turn_id)
            for k, v in fields.items():
                setattr(row, k, v)
            await db.commit()

    # ── 접속 / 해제 ───────────────────────────────────────────────────────────
    async def attach(self, ws: WebSocket) -> None:
        self.ws = ws
        self._last_client_seq = -1
        self._cancel("expire")
        self._cancel("grace")
        async with self._lock:  # detach 의 paused 기록과 경합하지 않도록 직렬화
            async with self.sm() as db:
                state = (await db.get(InterviewSession, self.session_id)).state
            if state in (SessionState.READY, SessionState.PAUSED, SessionState.CREATED):
                fields: dict[str, Any] = {"state": SessionState.IN_PROGRESS}
                if state != SessionState.PAUSED:
                    fields["started_at"] = _utcnow()
                await self._update_session(**fields)
                await self._mark_application_interviewing()
        cfg = self.cfg
        await self.send("session_ready", total_main=cfg.total_main, answer_limit_sec=cfg.answer_limit_sec,
                        max_followups=cfg.max_followups,
                        coding_test={"enabled": cfg.coding_enabled, "time_limit_sec": cfg.coding_limit_sec})
        await self._sync()

    async def _sync(self) -> None:
        """(재)접속 직후 현재 상태를 클라이언트에 재전송한다. 새 세션이면 첫 질문을 시작한다."""
        if self.phase in (Phase.CODING, Phase.FINISHED):
            await self.send("session_finished", next="coding" if self.phase == Phase.CODING else "done")
        elif self._recovered is not None:
            turn, text = self._recovered
            self._recovered = None
            self._spawn("pipeline", self._advance_after_answer(turn, SttResult(text), recovered=True))
        elif self.phase == Phase.IDLE and self.turn is None:
            self._spawn("advance", self._advance_main())
        elif self.phase in (Phase.ASKING, Phase.COUNTDOWN, Phase.AWAITING_START) and self.turn:
            self.phase = Phase.ASKING
            await self._announce(self.turn)  # 질문 재낭독 + 카운트다운부터 다시
        elif self.phase == Phase.ANSWERING and self.turn:
            await self._announce(self.turn, with_audio=False)  # 남은 시간만 알려 주고 답변은 계속
        elif self.phase == Phase.THINKING:
            await self.send("thinking", turn_id=str(self.turn.turn_id) if self.turn else None, stage=self._stage)

    async def detach(self, ws: WebSocket) -> None:
        """연결 해제. 이 메서드는 await 하지 않고 즉시 끝난다 — DB 기록·만료 예약은 핸들러가 취소되어도(서버 종료 등) 끝까지 실행되도록
        독립 태스크로 넘긴다."""
        if self.ws is not ws and self.ws is not None:
            return
        self.ws = None
        if self.closed:
            return
        if self.phase == Phase.FINISHED:
            self.release()
            return
        if self.phase in (Phase.ASKING, Phase.COUNTDOWN, Phase.AWAITING_START):
            self._cancel("audio")  # 클라이언트 없이 답변 창이 열리지 않도록 중단, 재접속 시 처음부터
            self.phase = Phase.ASKING
        elif self.phase == Phase.ANSWERING and self.turn:
            self._spawn("grace", self._grace_end(self.turn))
        self._spawn("detach", self._pause_and_expire())

    async def _pause_and_expire(self) -> None:
        async with self._lock:
            if self.ws is not None or self.closed:  # 그 사이 재접속했다면 일시정지하지 않는다
                return
            async with self.sm() as db:
                state = (await db.get(InterviewSession, self.session_id)).state
            if state == SessionState.IN_PROGRESS:
                await self._update_session(state=SessionState.PAUSED)
        self._spawn("expire", self._expire())

    async def _grace_end(self, turn: TurnState) -> None:
        await asyncio.sleep(self.eng.tuning.reconnect_grace_s)
        if self.ws is None:
            await self.end_answer(turn, "timeout")  # 디스크에 저장된 오디오까지 처리하고 진행 (TRD §4.5)

    async def _expire(self) -> None:
        await asyncio.sleep(self.eng.tuning.pause_ttl_s)
        if self.ws is None and not self.closed:
            await self._update_session(state=SessionState.ABORTED, ended_at=_utcnow())
            self.release()

    def release(self) -> None:
        self.close()
        if self.on_release:
            self.on_release(self.session_id)

    async def aclose(self) -> None:
        """종료: 태스크를 취소하고 실제로 끝날 때까지 기다린다 (DB 연결을 쓰는 중에 엔진이 닫히는 것을 막는다)."""
        pending = list(self._tasks.values()) + ([self._prefetch[1]] if self._prefetch else [])
        self.close()
        await asyncio.gather(*pending, return_exceptions=True)

    def close(self) -> None:
        self.closed = True
        for name in list(self._tasks):
            self._cancel(name)
        if self._prefetch:
            self._prefetch[1].cancel()
        if self.turn and self.turn.recording:
            self.turn.recording.close()
        if self.turn and self.turn.inc:
            self.turn.inc.cancel()

    # ── 질문 ──────────────────────────────────────────────────────────────────
    async def _begin_question(self, *, kind: TurnKind, text: str, category: str | None = None, evidence: list | None = None,
                              time_limit: int | None = None, parent_turn_id: uuid.UUID | None = None,
                              reason: str | None = None, text_mode: bool = False) -> TurnState:
        async with self._lock:
            main_index = self.main_asked if kind == TurnKind.MAIN else (self.turn.main_index if self.turn else 0)
            if kind == TurnKind.MAIN:
                self.main_asked += 1
                self.followup_count = 0
            else:
                self.followup_count += 1
            self.turn_no_counter += 1
            turn = TurnState(uuid.uuid4(), self.turn_no_counter, kind, main_index, text,
                             time_limit or self.cfg.answer_limit_sec, category, parent_turn_id, text_mode=text_mode)
            async with self.sm() as db:
                db.add(InterviewTurn(
                    id=turn.turn_id, session_id=self.session_id, turn_no=turn.turn_no, kind=kind, parent_turn_id=parent_turn_id,
                    main_index=main_index, question_text=text, question_category=category,
                    followup_reason=FollowupReason(reason) if reason in {r.value for r in FollowupReason} else None,
                    question_evidence=[e.model_dump() for e in (evidence or [])], asked_at=_utcnow()))
                sess = await db.get(InterviewSession, self.session_id)
                sess.current_turn_no, sess.followup_count = turn.turn_no, self.followup_count
                await db.commit()
            self.turn, self.phase = turn, Phase.ASKING
            self.asked.append(text)
        await self._announce(turn)
        if kind == TurnKind.MAIN:
            self._start_prefetch()
        return turn

    async def _announce(self, turn: TurnState, *, with_audio: bool = True) -> None:
        remaining = turn.time_limit_sec
        if turn.started_mono is not None:  # 답변 중 재접속: 남은 시간
            remaining = max(0, int(turn.time_limit_sec * self.eng.tuning.timeout_scale - (time.monotonic() - turn.started_mono)))
        await self.send("question", turn_id=str(turn.turn_id), turn_no=turn.turn_no, kind=turn.kind.value, text=turn.text,
                        progress={"main": turn.main_index + 1, "total": self.cfg.total_main}, time_limit_sec=remaining,
                        tts=not turn.text_mode, resumed=not with_audio)  # resumed: 답변 중 재접속 — 낭독·카운트다운 없이 이어서 답변
        if not with_audio or self.ws is None:
            return
        if turn.text_mode:
            self.phase = Phase.ANSWERING  # 코드 꼬리질문은 텍스트로 즉시 답변
            return
        self._tts_done.clear()
        self._answer_start.clear()
        self._spawn("audio", self._audio_flow(turn))

    async def _audio_flow(self, turn: TurnState) -> None:
        t = self.eng.tuning
        ok = await self._stream_tts(turn)
        try:  # TTS 실패 시 자막만 표시하고 유예 후 자동 진행, 클라이언트 tts_done 이 먼저 오면 즉시 진행
            await asyncio.wait_for(self._tts_done.wait(), t.tts_done_timeout_s if ok else t.tts_fail_grace_s)
        except asyncio.TimeoutError:
            pass
        await self._countdown(turn)

    async def _stream_tts(self, turn: TurnState) -> bool:
        idx, prev = 0, None
        try:
            async for chunk in self.eng.tts.synthesize(turn.text):
                if prev is not None:
                    await self._send_tts(turn, idx, prev, last=False)
                    idx += 1
                prev = chunk
            if prev is None:
                raise RuntimeError("empty audio")
            await self._send_tts(turn, idx, prev, last=True)
            return True
        except Exception as e:  # noqa: BLE001  TTS 실패는 세션을 중단시키지 않는다 (PRD 4.2 복구 요건)
            log.warning("tts failed: %s", type(e).__name__)
            await self.error("TTS_FAILED", "음성 합성에 실패해 자막으로 진행합니다", recoverable=True)
            return False

    async def _send_tts(self, turn: TurnState, idx: int, data: bytes, *, last: bool) -> None:
        await self.send("tts_chunk", turn_id=str(turn.turn_id), idx=idx, last=last, format=self.eng.tts.format,
                        data_b64=base64.b64encode(data).decode("ascii"))

    async def _countdown(self, turn: TurnState) -> None:
        t = self.eng.tuning
        self.phase = Phase.COUNTDOWN
        for n in (3, 2, 1):
            if self.phase != Phase.COUNTDOWN or self.turn is not turn:
                return  # 클라이언트가 먼저 answer_start 를 보냈거나 턴이 바뀜
            await self.send("countdown", turn_id=str(turn.turn_id), n=n)
            await t.countdown_sleep(t.countdown_step_s)
        if self.phase != Phase.COUNTDOWN or self.turn is not turn:
            return
        self.phase = Phase.AWAITING_START
        try:
            await asyncio.wait_for(self._answer_start.wait(), t.answer_start_grace_s)
        except asyncio.TimeoutError:
            await self.begin_answer(turn)  # answer_start 가 오지 않아도 교착되지 않도록 서버가 시작

    # ── 답변 ──────────────────────────────────────────────────────────────────
    async def begin_answer(self, turn: TurnState) -> bool:
        async with self._lock:
            if self.turn is not turn or self.phase not in (Phase.COUNTDOWN, Phase.AWAITING_START):
                return False
            t = self.eng.tuning
            turn.recording = self.eng.media.open_answer(self.session_id, turn.turn_id)
            turn.vad = EnergyVad(t.vad_rms)
            turn.inc = IncrementalStt(self.eng.stt, initial_prompt=t.initial_prompt)
            turn.started_mono = time.monotonic()
            self.phase = Phase.ANSWERING
        self._answer_start.set()
        await self._update_turn(turn.turn_id, answer_started_at=_utcnow(),
                                answer_audio_path=f"{self.session_id}/{turn.turn_id}.pcm")
        self._spawn("deadline", self._deadline(turn))
        return True

    async def _deadline(self, turn: TurnState) -> None:
        await asyncio.sleep(turn.time_limit_sec * self.eng.tuning.timeout_scale)
        await self.end_answer(turn, "timeout")

    def on_audio(self, pcm: bytes) -> bool:
        """미디어 채널의 오디오 청크. 답변 중이 아니면 버린다 (TTS 재생 중 자기 음성 유입 방지, TRD §4.2)."""
        turn = self.turn
        if self.phase != Phase.ANSWERING or turn is None or turn.recording is None:
            self.media_frames_dropped += 1
            return False
        turn.recording.append(pcm)  # 디스크에 즉시 append (NFR-Q2)
        turn.vad.feed(pcm)
        turn.inc.feed(pcm, turn.vad)
        if turn.vad.has_speech and turn.vad.silence_run_ms >= self.eng.tuning.silence_end_ms:
            self._spawn("silence", self.end_answer(turn, "silence"))
        return True

    async def end_answer(self, turn: TurnState, reason: str) -> bool:
        async with self._lock:
            if self.phase != Phase.ANSWERING or self.turn is not turn:
                return False  # 멱등: 이미 종료됨 (silence/timeout/user 경합)
            self.phase, self._stage = Phase.THINKING, "stt"
        self._cancel("deadline")
        self._cancel("grace")
        if turn.recording:
            turn.recording.close()
        await self._update_turn(turn.turn_id, answer_ended_at=_utcnow(), answer_end_reason=AnswerEndReason(reason),
                                answer_duration_ms=turn.recording.duration_ms if turn.recording else 0)
        await self.send("thinking", turn_id=str(turn.turn_id), stage="stt")
        self._spawn("pipeline", self._pipeline(turn))
        return True

    async def _pipeline(self, turn: TurnState) -> None:
        t = self.eng.tuning
        if turn.recording and turn.recording.duration_ms < t.min_answer_ms and turn.reasks < t.max_reasks:
            turn.inc.cancel()  # 1초 미만: "다시 말씀해 주세요" 재요청 (TRD §4.2)
            turn.recording.path.unlink(missing_ok=True)
            turn.reasks += 1
            # 첫 시도의 종료 기록을 지워야 /state 와 서버 재시작 복원이 "아직 답변 전인 턴"으로 올바르게 판별한다
            await self._update_turn(turn.turn_id, answer_started_at=None, answer_ended_at=None, answer_end_reason=None,
                                    answer_duration_ms=None)
            await self.error("ANSWER_TOO_SHORT", "다시 말씀해 주세요", recoverable=True)
            self.phase = Phase.COUNTDOWN
            self._answer_start.clear()
            self._spawn("audio", self._countdown(turn))
            return
        try:
            result = await turn.inc.finish()
        except Exception as e:  # noqa: BLE001  STT 일시 실패: 빈 답변으로 진행(세션 지속)
            log.warning("stt failed: %s", type(e).__name__)
            await self.error("STT_FAILED", "음성 인식이 잠시 지연되었습니다", recoverable=True)
            result = SttResult("", None, None)
        await self._update_turn(turn.turn_id, answer_text=result.text,
                                stt_meta={"avg_logprob": result.avg_logprob, "no_speech_prob": result.no_speech_prob,
                                          "model": getattr(self.eng.stt, "model_name", None)})
        await self.send("stt_final", turn_id=str(turn.turn_id), text=result.text, low_confidence=result.low_confidence)
        await self._advance_after_answer(turn, result)

    # ── 다음 질문 결정 ────────────────────────────────────────────────────────
    async def _advance_after_answer(self, turn: TurnState, result: SttResult, *, recovered: bool = False) -> None:
        cfg = self.cfg
        allowed = (turn.kind != TurnKind.CODE_FOLLOWUP and self.followup_count < cfg.max_followups
                   and any(cfg.triggers.values()))
        if allowed:
            self._stage = "analysis"
            await self.send("thinking", turn_id=str(turn.turn_id), stage="analysis")
            started: list[TurnState] = []

            async def on_ready(partial: FollowupDecision) -> None:  # question 필드가 닫히는 즉시 호출 → TTS 시작 (TRD §2.4)
                started.append(await self._begin_question(
                    kind=TurnKind.FOLLOWUP, text=partial.question or "", category=turn.category,
                    time_limit=cfg.answer_limit_sec, parent_turn_id=turn.turn_id, reason=partial.reason))

            ctx = FollowupContext(self.session_id, turn.turn_id, turn.text, result.text, result.low_confidence,
                                  list(self.asked), self.followup_count, cfg.max_followups)
            try:
                decision, _early = await self.eng.brain.decide_followup(ctx, on_ready)
            except LLMUnavailable:
                await self._mark_degraded("llm_unavailable", "AI 응답이 지연되어 꼬리질문 없이 진행합니다")
                decision = FollowupDecision.skip()
            if decision.needed:
                if started:  # 스트리밍 경로: 근거(evidence)는 후속 검증을 거쳐 뒤늦게 확정
                    await self._update_turn(started[0].turn_id, question_evidence=[e.model_dump() for e in decision.evidence])
                else:  # 비스트리밍 brain
                    await self._begin_question(kind=TurnKind.FOLLOWUP, text=decision.question or "", category=turn.category,
                                               evidence=decision.evidence, time_limit=cfg.answer_limit_sec,
                                               parent_turn_id=turn.turn_id, reason=decision.reason)
                return
        await self._advance_main()  # 메인 질문이 시작되면 _begin_question 이 꼬리질문 횟수를 초기화한다 (VOI-6)

    async def _advance_main(self) -> None:
        if self.main_asked >= self.cfg.total_main:
            await self._finish()
            return
        idx = self.main_asked
        pre, self._prefetch = self._prefetch, None
        if pre and pre[0] == idx:
            if not pre[1].done():
                self._stage = "generation"
                await self.send("thinking", turn_id=None, stage="generation")
            try:
                draft = await pre[1]
            except Exception:  # noqa: BLE001  prefetch 실패 시 직접 생성
                draft = await self.eng.brain.next_main_question(self.session_id, idx, list(self.asked))
        else:
            self._stage = "generation"
            await self.send("thinking", turn_id=None, stage="generation")
            draft = await self.eng.brain.next_main_question(self.session_id, idx, list(self.asked))
        if draft.degraded:
            await self._mark_degraded("llm_unavailable", "AI 응답이 지연되어 준비된 질문으로 진행합니다")
        await self._begin_question(kind=TurnKind.MAIN, text=draft.text, category=draft.category, evidence=draft.evidence,
                                   time_limit=draft.time_limit_sec)

    def _start_prefetch(self) -> None:
        """질문 N+1 사전 생성: 지원자가 N번에 답하는 동안 다음 메인 질문을 미리 만든다 (TRD §2.4)."""
        nxt = self.main_asked
        if nxt >= self.cfg.total_main or (self._prefetch and self._prefetch[0] == nxt):
            return
        if self._prefetch:
            self._prefetch[1].cancel()
        self._prefetch = (nxt, asyncio.create_task(self.eng.brain.next_main_question(self.session_id, nxt, list(self.asked))))

    async def _finish(self) -> None:
        coding = self.cfg.coding_enabled
        async with self._lock:
            self.phase = Phase.CODING if coding else Phase.FINISHED
        await self._update_session(state=SessionState.CODING if coding else SessionState.FINISHED,
                                  **({} if coding else {"ended_at": _utcnow()}))
        if not coding:  # 클라이언트가 POST /finish 를 부르지 못해도 지원 상태·리포트 잡이 누락되지 않게 한다 (멱등)
            from app.services.sessions import finalize_session

            await finalize_session(self.sm, self.session_id)
        await self.send("session_finished", next="coding" if coding else "done")

    async def _mark_degraded(self, reason: str, message: str) -> None:
        if not self.degraded:
            self.degraded = True
            await self._update_session(degraded_mode=True)
        await self.send("degraded", reason=reason, message=message)

    # ── 클라이언트 메시지 ─────────────────────────────────────────────────────
    async def handle_text(self, raw: str) -> None:
        try:
            msg = CLIENT_ADAPTER.validate_json(raw)
        except Exception:  # noqa: BLE001  잘못된 JSON/알 수 없는 type/필드 — 상세 입력은 되돌려주지 않는다
            await self.error("BAD_MESSAGE", "올바르지 않은 메시지입니다", recoverable=True)
            return
        if msg.seq is not None:
            if msg.seq <= self._last_client_seq:
                return  # 중복/역순 무시 (재전송 안전)
            self._last_client_seq = msg.seq
        await self.handle(msg)

    async def handle(self, msg: Any) -> None:
        turn = self.turn
        if isinstance(msg, Ping):
            await self.send("pong")
        elif isinstance(msg, Pong):
            return
        elif isinstance(msg, ResumeMsg):
            # 접속 시 현재 상태가 이미 재전송되었다. 클라이언트가 현재 턴을 모르는 경우에만 다시 보낸다.
            if turn and msg.last_turn_id != turn.turn_id and self.phase in (Phase.ASKING, Phase.COUNTDOWN, Phase.AWAITING_START,
                                                                          Phase.ANSWERING):
                await self._sync()
        elif isinstance(msg, GazeEventMsg):
            await self._on_gaze(msg)
        elif isinstance(msg, (TtsDone, AnswerStart, AnswerEnd, TextAnswer)):
            if turn is None or msg.turn_id != turn.turn_id:
                await self.error("BAD_TURN", "현재 질문과 일치하지 않는 요청입니다", recoverable=True)
                return
            if isinstance(msg, TtsDone):
                self._tts_done.set()
            elif isinstance(msg, AnswerStart):
                if not await self.begin_answer(turn) and self.phase != Phase.ANSWERING:
                    await self.error("BAD_STATE", "지금은 답변을 시작할 수 없습니다", recoverable=True)
            elif isinstance(msg, AnswerEnd):
                await self.end_answer(turn, msg.reason)
            else:
                await self._on_text_answer(turn, msg)

    async def _on_text_answer(self, turn: TurnState, msg: TextAnswer) -> None:
        """코드 꼬리질문의 텍스트 답변 (v2). 후속 처리(코드 근거 꼬리질문 반복)는 코딩테스트 연동 시 확장한다."""
        if not turn.text_mode or self.phase != Phase.ANSWERING:
            await self.error("BAD_STATE", "텍스트 답변을 받을 수 없는 상태입니다", recoverable=True)
            return
        async with self._lock:
            self.phase = Phase.THINKING
        await self._update_turn(turn.turn_id, answer_text=msg.text, answer_ended_at=_utcnow(),
                                answer_end_reason=AnswerEndReason.USER)
        await self._finish()

    async def _on_gaze(self, msg: GazeEventMsg) -> None:
        async with self.sm() as db:
            row = await db.get(InterviewTurn, msg.turn_id)
            if row is None or row.session_id != self.session_id:
                await self.error("BAD_TURN", "알 수 없는 질문입니다", recoverable=True)
                return
            base = row.answer_started_at or _utcnow()
            db.add(GazeEvent(session_id=self.session_id, turn_id=msg.turn_id, kind=msg.kind, start_ms=msg.start_ms,
                             end_ms=max(msg.end_ms, msg.start_ms), occurred_at=base + timedelta(milliseconds=msg.start_ms),
                             yaw=msg.yaw, pitch=msg.pitch, confidence=msg.confidence))
            await db.commit()
        if self.gaze_warnings < self.eng.tuning.gaze_warning_limit:
            self.gaze_warnings += 1
            await self.send("gaze_warning", count=self.gaze_warnings, message=GAZE_MESSAGES[msg.kind])
