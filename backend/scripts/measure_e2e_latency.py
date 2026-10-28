#!/usr/bin/env python3
"""운영 파이프라인 E2E 지연·메모리 측정 (TRD §9 V-3 / V-1) — 실제 서버(Ollama · faster-whisper · say)를 WebSocket 으로 구동한다.

`tests/benchmark_ai.py` 는 구성요소를 따로 재서 합산하지만, 이 스크립트는 **운영 경로 그대로**(증분 STT → 꼬리질문 스트리밍 → Guardrail → TTS)를
브라우저 없이 클라이언트처럼 흉내 내어 "답변 종료(answer_end 전송) → 다음 질문 음성 도착"을 턴마다 잰다.

  1) python scripts/dev_real_stack.py --port 8000          # 실제 엔진 스택 (별도 터미널, ollama serve 필요)
  2) python scripts/measure_e2e_latency.py --turns 100     # 표본이 --turns 개 모일 때까지 세션을 반복

측정 정의
  first_chunk  = answer_end 전송 → 다음 질문의 첫 tts_chunk 도착 (서버가 음성을 내보내기 시작한 시점)
  last_chunk   = answer_end 전송 → 마지막 tts_chunk 도착       (현재 프론트는 모든 청크를 모은 뒤 재생하므로 재생 시작의 상한)
  판정(V-3)은 보수적으로 last_chunk 를 쓰고 first_chunk 도 함께 보고한다. 다음 질문이 꼬리질문/메인 질문인지 나눠서도 보고한다.
한계 (결과 해석 시 반드시 함께 말할 것)
  * 답변 음성은 macOS `say` 합성음(--audio)이다. 실제 지원자 음성의 STT 정확도/속도와 다를 수 있다.
  * 브라우저·카메라(MediaPipe)·화면 렌더링 부하가 없다 → 메모리·CPU 는 실제 면접보다 낙관적이다. 메모리는 시스템 전체를 재므로 다른 앱 사용분이 포함된다.
  * 클라이언트는 TTS 재생을 기다리지 않고 마지막 청크를 받으면 바로 tts_done 을 보낸다(재생 시간은 지연에 포함되지 않는 구간이다).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import subprocess
import sys
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import httpx
import psutil
import websockets

REPO = Path(__file__).resolve().parents[2]
DEFAULT_AUDIO = REPO / "frontend" / "e2e" / "fixtures" / "answer-ko.wav"
PASSWORD = "Passw0rd!"
RESUME = {"name": "김지원", "education": [{"school": "한빛대학교", "major": "컴퓨터공학", "degree": "학사"}],
          "experience": [{"company": "다온커머스", "role": "백엔드 인턴", "summary": "주문 조회 API의 응답 시간을 Redis 캐시로 개선하고 장애 대응을 맡았습니다."}],
          "projects": [{"title": "주문 API 성능 개선", "role": "개발", "tech_stack": ["Java", "Spring", "Redis"], "description": "캐시 도입으로 평균 응답 시간을 800ms에서 200ms로 줄였습니다."}],
          "skills": ["Java", "Spring", "Redis", "MySQL"]}


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if not s:
        return float("nan")
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "p50": round(pct(xs, 0.5), 2), "p95": round(pct(xs, 0.95), 2), "mean": round(statistics.fmean(xs), 2), "min": round(min(xs), 2), "max": round(max(xs), 2)}


class MemSampler(threading.Thread):
    """1초 간격으로 시스템 전체 사용량(total-available)·스왑·서버/Ollama RSS 를 기록한다."""

    def __init__(self, server_port: int):
        super().__init__(daemon=True)
        self.stop_ev = threading.Event()
        self.server_port = server_port
        self.rows: list[dict] = []
        self.baseline = self._snap()

    def _pids(self) -> tuple[int | None, list[int]]:
        """서버 PID 는 포트 리스너(macOS 에서는 권한이 필요)가 아니라 명령줄로 찾는다."""
        servers, oll = [], []
        for p in psutil.process_iter(["name", "cmdline"]):
            cmd = " ".join(p.info["cmdline"] or [])
            if "python" in (p.info["name"] or "").lower() and ("dev_real_stack" in cmd or ("uvicorn" in cmd and f"--port {self.server_port}" in cmd)):
                servers.append(p)
            if "ollama" in (p.info["name"] or "").lower():
                oll.append(p.pid)
        best = max(servers, key=lambda p: p.memory_info().rss, default=None)  # 래퍼 셸이 아니라 실제 서버(가장 큰 RSS)
        return (best.pid if best else None), oll

    def _snap(self) -> dict:
        vm, sw = psutil.virtual_memory(), psutil.swap_memory()
        try:
            server, oll = self._pids()
        except (psutil.AccessDenied, OSError):
            server, oll = None, []

        def rss(pids: list[int]) -> float:
            t = 0
            for pid in pids:
                try:
                    t += psutil.Process(pid).memory_info().rss
                except psutil.Error:
                    pass
            return t / 1024**3

        try:  # Ollama 가 적재한 모델 크기(통합 메모리). RSS 에 다 잡히지 않을 수 있어 따로 기록한다.
            ps = httpx.get("http://127.0.0.1:11434/api/ps", timeout=1.0).json().get("models", [])
            loaded = sum(m.get("size", 0) for m in ps) / 1024**3
        except Exception:  # noqa: BLE001
            loaded = 0.0
        return {"t": time.time(), "ollama_loaded_gb": loaded, "system_used_gb": (vm.total - vm.available) / 1024**3, "swap_gb": sw.used / 1024**3,
                "server_rss_gb": rss([server]) if server else 0.0, "ollama_rss_gb": rss(oll)}

    def run(self) -> None:
        while not self.stop_ev.is_set():
            self.rows.append(self._snap())
            self.stop_ev.wait(1.0)

    def report(self) -> dict:
        if not self.rows:
            return {}
        peak = lambda k: round(max(r[k] for r in self.rows), 2)  # noqa: E731
        return {"samples": len(self.rows), "baseline_system_used_gb": round(self.baseline["system_used_gb"], 2), "baseline_swap_gb": round(self.baseline["swap_gb"], 2),
                "peak_system_used_gb": peak("system_used_gb"), "peak_swap_gb": peak("swap_gb"), "swap_increase_gb": round(peak("swap_gb") - self.baseline["swap_gb"], 2),
                "peak_server_rss_gb": peak("server_rss_gb"), "peak_ollama_rss_gb": peak("ollama_rss_gb"), "peak_ollama_loaded_model_gb": peak("ollama_loaded_gb")}


def load_pcm(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, 16000, 2), "16kHz mono PCM16 WAV 만 지원"
        return w.readframes(w.getnframes())


async def prepare_session(http: httpx.AsyncClient, tag: str) -> tuple[str, float]:
    t0 = time.monotonic()
    email = f"lat-{tag}-{int(time.time())}@corp.local"
    r = await http.post("/api/v1/auth/register", json={"name": "지연측정", "email": email, "password": PASSWORD, "password_confirm": PASSWORD,
                                                       "birth_date": "1999-01-01", "gender": "female", "phone": "010-1234-5678"})
    r.raise_for_status()
    jobs = (await http.get("/api/v1/jobs")).json()["items"]
    job = next(j for j in jobs if j["title"].startswith("백엔드"))
    app_id = (await http.post(f"/api/v1/jobs/{job['id']}/apply", json={"consent": True, "consent_version": "2026-01"})).json()["application_id"]
    (await http.put(f"/api/v1/applications/{app_id}/resume", json={"source": "manual", "data": RESUME})).raise_for_status()
    sid = (await http.post(f"/api/v1/applications/{app_id}/session")).json()["session_id"]
    (await http.post(f"/api/v1/sessions/{sid}/device-check", json={"camera": True, "mic": True, "speaker": True, "devices": {}})).raise_for_status()
    for _ in range(240):
        r = await http.post(f"/api/v1/sessions/{sid}/start")
        if r.status_code == 200:
            return sid, time.monotonic() - t0
        if r.status_code == 409:
            raise RuntimeError(f"start 409: {r.text[:200]}")
        await asyncio.sleep(1)
    raise TimeoutError("start 대기 초과")


async def run_session(http: httpx.AsyncClient, base_ws: str, sid: str, pcm: bytes, rng: random.Random, session_idx: int, want: int, have: int) -> list[dict]:
    """세션 하나를 끝까지(또는 표본이 충분할 때까지) 진행하며 턴 전환 지연을 기록한다."""
    tok = (await http.post(f"/api/v1/sessions/{sid}/ws-token")).json()
    samples: list[dict] = []
    seq = 0
    async with websockets.connect(f"{base_ws}/ws/sessions/{sid}/control?token={tok['control_token']}", max_size=None) as ctl:
        media = None  # 서버는 control 이 먼저 연결·session_ready 된 뒤에만 media 를 받는다 (프론트도 같은 순서)
        cur: dict = {}                 # 현재 질문의 도착 정보
        pending: dict | None = None    # 마지막 answer_end 정보 (다음 질문 도착 대기 중)
        stages: list[tuple[str, float]] = []
        answer_task: asyncio.Task | None = None
        n_answers = 0

        async def speak() -> float:
            nonlocal seq
            await asyncio.sleep(0.2)  # 클라이언트의 ANSWER_START_DELAY
            secs = rng.uniform(10.0, min(20.0, len(pcm) / 32000))
            step = 16000  # 500ms PCM16 = 16000 B
            total = int(secs * 32000) // step * step
            t_start = time.monotonic()
            for off in range(0, total, step):
                await media.send(bytes([1]) + seq.to_bytes(4, "big") + pcm[off:off + step])
                seq += 1
                await asyncio.sleep(max(0.0, t_start + (off + step) / 32000 - time.monotonic()))  # 실시간 속도 (증분 STT 부하를 현실적으로)
            return secs

        async def end_answer(turn_id: str) -> None:
            nonlocal pending, stages
            await speak()
            stages = []
            await ctl.send(json.dumps({"type": "answer_end", "turn_id": turn_id, "reason": "user"}))
            pending = {"t_end": time.monotonic(), "from_kind": cur.get("kind"), "chunks": []}

        async for raw in ctl:
            now = time.monotonic()
            m = json.loads(raw)
            t = m["type"]
            if t == "ping":
                await ctl.send(json.dumps({"type": "pong"}))
            elif t == "session_ready" and media is None:
                media = await websockets.connect(f"{base_ws}/ws/sessions/{sid}/media?token={tok['media_token']}", max_size=None)
            elif t == "question" and not m.get("resumed"):
                cur = {"turn_id": m["turn_id"], "kind": m["kind"], "arrived": now}
                if pending is not None:
                    pending["next_kind"], pending["t_question"] = m["kind"], now
            elif t == "thinking":
                stages.append((m["stage"], now))
            elif t == "tts_chunk":
                if pending is not None and m["turn_id"] == cur["turn_id"]:
                    pending["chunks"].append(now)
                if m["last"]:
                    if pending is not None and pending["chunks"]:
                        t_end = pending["t_end"]
                        samples.append({"session": session_idx, "from_kind": pending["from_kind"], "next_kind": pending.get("next_kind"),
                                        "first_chunk_s": pending["chunks"][0] - t_end, "last_chunk_s": pending["chunks"][-1] - t_end,
                                        "question_msg_s": pending.get("t_question", now) - t_end,
                                        "stages_s": {s: round(ts - t_end, 2) for s, ts in stages}})
                        print(f"  [{len(samples) + have:>3}/{want}] {pending['from_kind']}→{pending.get('next_kind')}: first {samples[-1]['first_chunk_s']:.2f}s last {samples[-1]['last_chunk_s']:.2f}s", flush=True)
                        pending = None
                    await ctl.send(json.dumps({"type": "tts_done", "turn_id": m["turn_id"]}))
            elif t == "countdown" and m["n"] == 1:
                await asyncio.sleep(0.3)
                await ctl.send(json.dumps({"type": "answer_start", "turn_id": m["turn_id"]}))
                n_answers += 1
                answer_task = asyncio.create_task(end_answer(m["turn_id"]))
            elif t == "session_finished":
                break
            elif t == "error" and not m.get("recoverable", True):
                raise RuntimeError(f"서버 오류: {m}")
            if len(samples) + have >= want and pending is None and (answer_task is None or answer_task.done()):
                break
        if answer_task and not answer_task.done():
            answer_task.cancel()
        if media is not None:
            await media.close()
    await http.post(f"/api/v1/sessions/{sid}/finish")  # 슬롯 반환 (런타임 정리)
    return samples


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--turns", type=int, default=100, help="모을 표본 수(답변 종료 → 다음 질문 전환 횟수)")
    ap.add_argument("--max-sessions", type=int, default=60)
    ap.add_argument("--audio", type=Path, default=DEFAULT_AUDIO)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=REPO / "data" / "benchmarks")
    a = ap.parse_args()
    pcm = load_pcm(a.audio)
    rng = random.Random(a.seed)
    base_ws = a.base.replace("http", "ws", 1)
    port = int(a.base.rsplit(":", 1)[1])
    sampler = MemSampler(port)
    sampler.start()
    started = datetime.now().isoformat(timespec="seconds")
    all_samples: list[dict] = []
    preps: list[float] = []
    async with httpx.AsyncClient(base_url=a.base, timeout=60) as http:
        for i in range(a.max_sessions):
            if len(all_samples) >= a.turns:
                break
            http.cookies.clear()
            print(f"세션 {i + 1}: 준비 중…", flush=True)
            try:
                sid, prep = await prepare_session(http, str(i))
            except Exception as e:  # noqa: BLE001
                print(f"  준비 실패: {type(e).__name__}: {e}", flush=True)
                continue
            preps.append(prep)
            print(f"  준비 {prep:.1f}s", flush=True)
            try:
                all_samples += await run_session(http, base_ws, sid, pcm, rng, i, a.turns, len(all_samples))
            except Exception as e:  # noqa: BLE001
                print(f"  세션 실패: {type(e).__name__}: {e}", flush=True)
    sampler.stop_ev.set()
    sampler.join(timeout=3)

    warm = [s for s in all_samples if s["session"] > 0]  # 첫 세션은 모델 콜드 로드가 섞인다
    def col(rows: list[dict], key: str, kind: str | None = None) -> list[float]:
        return [r[key] for r in rows if kind is None or r["next_kind"] == kind]
    result = {
        "started": started, "finished": datetime.now().isoformat(timespec="seconds"), "turns_requested": a.turns, "samples": len(all_samples), "sessions": len(preps),
        "prep_s": summarize(preps),
        "last_chunk_all": summarize(col(all_samples, "last_chunk_s")), "first_chunk_all": summarize(col(all_samples, "first_chunk_s")),
        "last_chunk_excluding_first_session": summarize(col(warm, "last_chunk_s")),
        "by_next_kind": {k: {"last_chunk": summarize(col(all_samples, "last_chunk_s", k)), "first_chunk": summarize(col(all_samples, "first_chunk_s", k))}
                         for k in sorted({s["next_kind"] for s in all_samples if s["next_kind"]})},
        "memory": sampler.report(), "raw": all_samples,
        "gate": {"p50_s": 9.5, "p95_s": 12.0, "memory_peak_gb": 14.5},
    }
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"v3_e2e_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print("\n" + json.dumps({k: v for k, v in result.items() if k != "raw"}, ensure_ascii=False, indent=1))
    print(f"\n결과 저장: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
