"""README 아키텍처 흐름도(로고 기반) 소스 생성기.

    python3 docs/assets/architecture/build_flow.py   # -> architecture-flow.html
    (PNG: cd frontend && npx playwright test -c playwright.capture.config.ts -g "아키텍처 흐름")

로고는 simple-icons(CC0) SVG 를 logos/ 에 내려받아 쓴다. 없는 로고(Whisper·ChromaDB·Monaco 등)는 아래 ICONS 의 직접 그린 아이콘.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).parent


def logo(name: str, color: str) -> str:
    svg = (HERE / "logos" / f"{name}.svg").read_text(encoding="utf-8")
    svg = re.sub(r"<title>.*?</title>", "", svg)
    return svg.replace("<svg ", f'<svg fill="{color}" ', 1)


def stroke(body: str, color: str) -> str:
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" '
            f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


T = "#0f766e"
ICONS = {
    "mic": lambda c=T: stroke('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>', c),
    "cam": lambda c=T: stroke('<rect x="3" y="6" width="12" height="12" rx="2"/><path d="m15 10 6-3v10l-6-3"/>', c),
    "wave": lambda c="#7c3aed": stroke('<path d="M3 12h2M7 7v10M11 4v16M15 8v8M19 10v4M22 12h-1"/>', c),
    "db": lambda c="#e11d48": stroke('<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>', c),
    "folder": lambda c="#b45309": stroke('<path d="M3 7a2 2 0 0 1 2-2h4l2 2.5h8a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', c),
    "code": lambda c="#2563eb": stroke('<path d="m8 8-4 4 4 4M16 8l4 4-4 4M13.5 6l-3 12"/>', c),
    "shield": lambda c=T: stroke('<path d="M12 3 5 6v6c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z"/><path d="m9 12 2.2 2.2L15.5 10"/>', c),
    "lock": lambda c=T: stroke('<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>', c),
    "gear": lambda c=T: stroke('<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1"/>', c),
    "doc": lambda c=T: stroke('<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>', c),
    "speaker": lambda c="#7c3aed": stroke('<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>', c),
    "chip": lambda c=T: stroke('<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3"/>', c),
}


def tile(icon: str, title: str, cap: str, big: bool = False) -> str:
    return f'<div class="tile{" big" if big else ""}"><div class="ic">{icon}</div><b>{title}</b><span>{cap}</span></div>'


def pill(icon: str, text: str) -> str:
    return f'<div class="pillx"><i>{icon}</i>{text}</div>'


CSS = """
*{box-sizing:border-box;margin:0}
body{width:1600px;background:#fff;font-family:"Pretendard","Apple SD Gothic Neo","Noto Sans KR",sans-serif;color:#0f172a;padding:16px 40px 40px}
.head{display:flex;align-items:center;gap:14px;margin-bottom:6px}
.head h1{font-size:27px;font-weight:800}
.badge{background:#111827;color:#5eead4;font-size:13px;font-weight:700;border-radius:999px;padding:5px 14px}
.sub{color:#64748b;font-size:15px;margin-bottom:30px}
.grid{position:relative;margin-top:66px;display:grid;grid-template-columns:350px 150px 400px 150px 460px;grid-template-rows:auto auto;column-gap:0;row-gap:26px}
.server{grid-area:1/3/3/6;margin:-48px -14px -14px -14px;border:2px dashed #5eead4;border-radius:26px;background:linear-gradient(180deg,#f0fdfa,#fff 55%);z-index:0}
.stag{grid-area:1/3/2/6;align-self:start;margin:-63px 0 0 14px;z-index:2;justify-self:start;font-size:13.5px;font-weight:700;color:#0f766e;background:#fff;border:1.5px solid #99f6e4;border-radius:999px;padding:3px 14px;display:flex;gap:7px;align-items:center}
.stag svg{width:15px;height:15px}
.grp{position:relative;z-index:1;border:1.5px solid #e2e8f0;border-radius:20px;background:#fff;padding:36px 18px 18px;box-shadow:0 6px 18px rgba(15,23,42,.05)}
.grp>.t{position:absolute;top:-14px;left:18px;font-size:14px;font-weight:800;color:#fff;border-radius:999px;padding:4px 15px;letter-spacing:.2px}
.g-b .t{background:#2563eb}.g-s .t{background:#0f766e}.g-a .t{background:#7c3aed}.g-d .t{background:#b45309}
.g-b{grid-area:1/1/3/2;display:flex;flex-direction:column;justify-content:center}
.g-s{grid-area:1/3/3/4;display:flex;flex-direction:column;justify-content:center;gap:16px}
.g-a{grid-area:1/5/2/6}.g-d{grid-area:2/5/3/6}
.tiles{display:flex;flex-wrap:wrap;gap:12px}
.tile{width:calc(50% - 6px);border:1.5px solid #e2e8f0;border-radius:16px;background:#f8fafc;padding:14px 8px 12px;text-align:center}
.g-a .tile,.g-d .tile{width:calc(25% - 9px);padding:14px 4px 12px}
.tile .ic{width:50px;height:50px;margin:0 auto 9px;display:flex;align-items:center;justify-content:center}
.tile .ic svg{width:46px;height:46px}
.tile b{display:block;font-size:14.5px;margin-bottom:3px}
.tile span{display:block;font-size:12px;line-height:1.4;color:#64748b}
.tile.big{width:100%;display:flex;align-items:center;gap:18px;text-align:left;padding:16px 20px;background:#f0fdfa;border-color:#99f6e4}
.tile.big .ic{margin:0;width:64px;height:64px;flex:none}.tile.big .ic svg{width:60px;height:60px}
.tile.big b{font-size:19px}.tile.big span{font-size:13px}
.pills{display:flex;flex-wrap:wrap;gap:10px}
.pillx{display:flex;align-items:center;gap:8px;border:1.5px solid #99f6e4;background:#fff;color:#115e59;border-radius:12px;padding:9px 13px;font-size:14px;font-weight:700;width:calc(50% - 5px)}
.pillx i{width:21px;height:21px;display:flex}.pillx i svg{width:21px;height:21px}
.pair{display:flex;gap:12px}.pair .tile{width:50%}
.arr{position:relative;z-index:1;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:7px;padding:0 8px}
.a1{grid-area:1/2/3/3}.a2{grid-area:1/4/2/5}.a3{grid-area:2/4/3/5}
.lab{font-size:12.5px;line-height:1.35;text-align:center;color:#334155;background:#fff;border:1.5px solid #cbd5e1;border-radius:10px;padding:5px 8px;width:100%}
.lab b{display:block;color:#0f766e;font-size:12.5px}
.line{height:0;width:100%;border-top:3px solid #0f766e;position:relative;margin:2px 0}
.line.both:before,.line.both:after{content:"";position:absolute;top:-8px;border:6.5px solid transparent}
.line.both:before{left:-3px;border-right:10px solid #0f766e;border-left:0}
.line.both:after{right:-3px;border-left:10px solid #0f766e;border-right:0}
.turn{margin-top:42px;border:1.5px solid #e2e8f0;border-radius:20px;padding:24px 28px 22px;background:#fafafa;position:relative}
.turn>.t{position:absolute;top:-14px;left:24px;background:#0f172a;color:#fff;font-size:14px;font-weight:800;border-radius:999px;padding:4px 16px}
.steps{display:flex;align-items:flex-start;justify-content:space-between}
.st{width:190px;text-align:center}
.st .c{width:74px;height:74px;border-radius:50%;background:#fff;border:2.5px solid #0f766e;margin:0 auto 10px;display:flex;align-items:center;justify-content:center;position:relative}
.st .c svg{width:38px;height:38px}
.st .c u{position:absolute;top:-8px;left:-8px;width:26px;height:26px;border-radius:50%;background:#0f766e;color:#fff;font:800 13px/26px sans-serif;text-decoration:none}
.st b{display:block;font-size:15px;margin-bottom:3px}.st span{font-size:12.5px;color:#64748b;line-height:1.4;display:block}
.nx{flex:none;align-self:flex-start;margin-top:26px;width:34px;height:22px;position:relative}
.nx:before{content:"";position:absolute;left:0;right:6px;top:10px;border-top:3px solid #0f766e}
.nx:after{content:"";position:absolute;right:0;top:3px;border:8px solid transparent;border-left:11px solid #0f766e;border-right:0}
.note{margin-top:14px;font-size:13px;color:#64748b;text-align:center}
"""


def build() -> str:
    blue, gray = "#2563eb", "#0f172a"
    b = '<div class="grp g-b"><div class="t">브라우저 · 지원자 / 채용 담당자</div><div class="tiles">' + "".join([
        tile(logo("nextdotjs", gray), "Next.js 14", "화면 · 상태 관리"),
        tile(logo("mediapipe", "#0097a7"), "MediaPipe", "시선 이탈 감지 (WASM)"),
        tile(ICONS["mic"]() + "", "음성·영상 녹화", "마이크 · 카메라 스트림"),
        tile(ICONS["code"](blue), "Monaco 에디터", "코딩테스트 풀이"),
    ]) + "</div></div>"
    s = '<div class="grp g-s"><div class="t">백엔드 · FastAPI</div>' + tile(logo("fastapi", "#009688"), "FastAPI 서버", "REST + WebSocket · Python 3.11 · 단일 프로세스", big=True) \
        + '<div class="pair">' + tile(logo("pydantic", "#e92063"), "Pydantic", "AI 출력 검증") + tile(logo("sqlalchemy", "#d71f00"), "SQLAlchemy", "DB 접근 · 마이그레이션") + "</div>" \
        + '<div class="pills">' + pill(ICONS["gear"](), "면접 세션 런타임") + pill(ICONS["shield"](), "Guardrail 검증") + pill(ICONS["doc"](), "리포트 워커") + pill(ICONS["lock"](), "인증 · 권한") + "</div></div>"
    a = '<div class="grp g-a"><div class="t">AI 엔진 · 모두 로컬 실행</div><div class="tiles">' + "".join([
        tile(logo("ollama", gray), "Ollama", "LLM<br>Qwen2.5-7B"),
        tile(ICONS["wave"](), "Whisper", "STT<br>faster-whisper"),
        tile(ICONS["speaker"](), "음성 합성", "TTS<br>질문 낭독"),
        tile(ICONS["db"]() , "ChromaDB", "이력서 검색<br>bge-m3"),
    ]) + "</div></div>"
    d = '<div class="grp g-d"><div class="t">데이터 · 실행 환경</div><div class="tiles">' + "".join([
        tile(logo("postgresql", "#4169e1"), "PostgreSQL", "운영 DB"),
        tile(logo("sqlite", "#003b57"), "SQLite", "개발 · 테스트"),
        tile(logo("docker", "#2496ed"), "Docker", "코딩 샌드박스"),
        tile(ICONS["folder"](), "로컬 파일", "음성 · 영상 · PDF"),
    ]) + "</div></div>"
    a1 = '<div class="arr a1"><div class="lab"><b>REST</b>공고 · 이력서 · 리포트</div><div class="line both"></div><div class="lab"><b>WS 제어</b>질문 · 자막 · 시선</div><div class="line both"></div><div class="lab"><b>WS 미디어</b>음성 · 영상 청크</div></div>'
    a2 = '<div class="arr a2"><div class="lab"><b>AI 호출</b>질문 생성 · 음성 인식<br>음성 합성 · 근거 검색</div><div class="line both"></div></div>'
    a3 = '<div class="arr a3"><div class="lab"><b>저장 · 실행</b>문답 기록 · 파일<br>코드 샌드박스 실행</div><div class="line both"></div></div>'
    server_tag = f'<div class="stag">{ICONS["lock"]()}내부망 · Mac M2 Pro 16GB · 외부 API 호출 0</div>'

    def st(n, ic, t, c):
        return f'<div class="st"><div class="c"><u>{n}</u>{ic}</div><b>{t}</b><span>{c}</span></div>'
    nx = '<div class="nx"></div>'
    turn = '<div class="turn"><div class="t">면접 한 턴의 흐름</div><div class="steps">' + nx.join([
        st(1, ICONS["mic"](), "답변", "말하는 동안 구간별로<br>미리 받아 적기"),
        st(2, ICONS["wave"](), "음성 인식", "마지막 구간만<br>답변 종료 후 처리"),
        st(3, ICONS["db"](), "근거 검색", "이력서에서 관련<br>문장 찾기"),
        st(4, logo("ollama", gray), "꼬리질문 생성", "LLM이 JSON을<br>스트리밍으로 생성"),
        st(5, ICONS["shield"](), "Guardrail", "근거 · 인적 속성 ·<br>중복 · 길이 검사"),
        st(6, ICONS["speaker"](), "음성 재생", "질문 필드가 완성되는<br>즉시 읽어주기"),
    ]) + "</div></div>"
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>{CSS}</style></head><body>'
            f'<div class="grid" id="arch"><div class="server"></div>{server_tag}{b}{a1}{s}{a2}{a}{a3}{d}</div>{turn}</body></html>')


if __name__ == "__main__":
    (HERE / "architecture-flow.html").write_text(build(), encoding="utf-8")
    print("ok")
