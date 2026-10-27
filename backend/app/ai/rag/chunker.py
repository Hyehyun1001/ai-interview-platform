"""Chunking 전략 (TRD §3.2). 구조화된 단위(섹션)를 우선하고, 길이 초과 시에만 재귀 분할한다.

토큰 수는 한국어 기준 근사(1토큰 ≈ 1.5자)로 환산한 글자 수로 제한한다 — 정확한 토크나이저 없이도 상한을 지키기 위함.
모든 chunk 에 `chunk_id` 를 부여해 질문의 근거 인용(citation)에 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.resume import ResumeSchema

CHARS_PER_TOKEN = 1.5


def tok(n_tokens: int) -> int:
    return int(n_tokens * CHARS_PER_TOKEN)


EXPERIENCE_MAX, PROJECT_MAX, PROFILE_MAX, JD_MAX = tok(400), tok(400), tok(300), tok(300)
EXPERIENCE_OVERLAP = PROJECT_OVERLAP = tok(50)
SELF_INTRO_MAX, SELF_INTRO_OVERLAP = tok(500), tok(80)
SEPARATORS = ["\n\n", "\n", "다. ", ". ", " "]  # TRD §3.2 한글 구분자


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


def recursive_split(text: str, max_chars: int, overlap: int = 0, separators: list[str] | None = None) -> list[str]:
    """큰 구분자부터 시도해 max_chars 이하 조각으로 나눈다. 구분자가 없으면 글자 단위로 자른다."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    seps = SEPARATORS if separators is None else separators
    if not seps:  # 구분자 소진 → 하드 분할
        step = max(1, max_chars - overlap)
        return [text[i:i + max_chars] for i in range(0, len(text), step)]
    sep, rest = seps[0], seps[1:]
    if sep not in text:
        return recursive_split(text, max_chars, overlap, rest)
    parts = [p + (sep if i < text.count(sep) else "") for i, p in enumerate(text.split(sep))]
    pieces: list[str] = []
    for part in parts:  # 조각 하나가 여전히 크면 더 작은 구분자로 재분할
        pieces.extend(recursive_split(part, max_chars, overlap, rest) if len(part) > max_chars else [part])
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        if cur and len(cur) + len(piece) > max_chars:
            chunks.append(cur.strip())
            tail = cur[-overlap:] if overlap else ""  # 앞 chunk 꼬리를 겹쳐 문맥 유지 — 겹침을 포함해도 max_chars 를 넘지 않게 줄인다
            allowed = max_chars - len(piece)
            cur = (tail[len(tail) - allowed:] if 0 < allowed < len(tail) else tail if allowed >= len(tail) else "") + piece
        else:
            cur += piece
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if c]


def _period(start: str | None, end: str | None) -> str:
    return f"{start or ''}~{end or ''}".strip("~") if (start or end) else ""


def chunk_resume(snapshot_id: str, resume: ResumeSchema) -> list[Chunk]:
    """이력서 → chunk. 경력 1건 = 1 chunk, 프로젝트 1건 = 1 chunk, 학력/기술/자격 = 1 chunk, 자소서 = 문단 분할."""
    chunks: list[Chunk] = []

    def add(section: str, idx: int, text: str, **meta: str | int | float | bool) -> None:
        chunks.append(Chunk(f"{snapshot_id}:{section}:{idx}", text, {"section": section, **{k: v for k, v in meta.items() if v != ""}}))

    for i, e in enumerate(resume.experience):
        body = "\n".join(filter(None, [f"[경력] {e.company or ''} / {e.role or ''} / {_period(e.start, e.end)}".strip(), e.summary or ""]))
        for j, piece in enumerate(recursive_split(body, EXPERIENCE_MAX, EXPERIENCE_OVERLAP)):
            add("experience", i * 100 + j, piece, company=e.company or "", period=_period(e.start, e.end))
    for i, p in enumerate(resume.projects):
        head = f"[프로젝트] {p.title or ''} / {p.role or ''} / {p.period or ''}".strip()
        stack = f"기술스택: {', '.join(p.tech_stack)}" if p.tech_stack else ""
        body = "\n".join(filter(None, [head, stack, p.description or ""]))
        for j, piece in enumerate(recursive_split(body, PROJECT_MAX, PROJECT_OVERLAP)):
            add("project", i * 100 + j, piece, title=p.title or "", tech_stack=",".join(p.tech_stack))
    profile_lines = [f"성명: {resume.name}"] if resume.name else []
    profile_lines += [f"[학력] {e.school or ''} {e.major or ''} {e.degree or ''} {_period(e.start, e.end)}".strip() for e in resume.education]
    if resume.skills:
        profile_lines.append("[기술] " + ", ".join(resume.skills))
    if resume.certifications:
        profile_lines.append("[자격] " + ", ".join(resume.certifications))
    for j, piece in enumerate(recursive_split("\n".join(profile_lines), PROFILE_MAX)):
        add("profile", j, piece)
    for j, piece in enumerate(recursive_split(resume.self_intro or "", SELF_INTRO_MAX, SELF_INTRO_OVERLAP)):
        add("self_intro", j, piece, para_idx=j)
    return chunks


JD_SECTIONS = {"requirements": "jd_req", "preferred": "jd_pref", "duties": "jd_duty"}


def chunk_jd(job_id: str, *, requirements: str | None, preferred: str | None, duties: str | None) -> list[Chunk]:
    """공고 JD → 항목(요건/우대/업무) 단위 chunk."""
    chunks: list[Chunk] = []
    for attr, text in (("requirements", requirements), ("preferred", preferred), ("duties", duties)):
        section = JD_SECTIONS[attr]
        for j, piece in enumerate(recursive_split(text or "", JD_MAX)):
            chunks.append(Chunk(f"{job_id}:{section}:{j}", piece, {"section": section}))
    return chunks
