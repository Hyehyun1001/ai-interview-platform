"""이력서 PDF 검증·텍스트 추출·정규화·섹션 분리 (TRD §3.1, RAG-1/2).

* 업로드 검증: 확장자 + MIME + 매직바이트(%PDF-) 이중 검사, 최대 10MB / 20쪽, 암호화·손상 파일 거부.
* 텍스트 레이어가 있으면 PyMuPDF, 없는 페이지만 OCR(Tesseract kor+eng) — 가벼운 경로 우선.
* 운영에서는 `parse_pdf_isolated` 로 별도 서브프로세스(타임아웃 30s)에서 실행한다 (TRD §8.3: 파서 격리).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.ai.rag import ocr

MAX_PDF_BYTES = 10 * 1024 * 1024
MAX_PAGES = 20
MIN_PAGE_CHARS = 20  # 이보다 적으면 텍스트 레이어가 없는 페이지로 보고 OCR 대상
PARSE_TIMEOUT_S = 30
BACKEND_DIR = Path(__file__).resolve().parents[3]


class PdfError(Exception):
    """사용자에게 그대로 보여줄 수 있는 메시지를 가진 업로드/파싱 오류. http_status 는 API 계층이 사용."""

    def __init__(self, code: str, message: str, http_status: int):
        super().__init__(message)
        self.code, self.message, self.http_status = code, message, http_status


def validate_pdf_upload(filename: str, content_type: str | None, data: bytes) -> int:
    """검증 후 페이지 수를 반환. 다른 확장자는 업로드 시점에 거부하고 사유를 안내한다 (RAG-1)."""
    not_pdf = PdfError("UNSUPPORTED_MEDIA_TYPE", "PDF 파일만 업로드할 수 있습니다.", 415)
    if not filename.lower().endswith(".pdf"):
        raise not_pdf
    if (content_type or "").split(";")[0].strip().lower() != "application/pdf":
        raise not_pdf
    if not data.startswith(b"%PDF-"):
        raise not_pdf
    if len(data) > MAX_PDF_BYTES:
        raise PdfError("PAYLOAD_TOO_LARGE", "10MB 이하의 PDF만 업로드할 수 있습니다.", 413)
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001  손상 파일
        raise PdfError("CORRUPT_PDF", "파일을 읽을 수 없습니다. 다른 파일을 올리거나 직접 작성해 주세요.", 422) from e
    with doc:
        if doc.needs_pass or doc.is_encrypted:
            raise PdfError("ENCRYPTED_PDF", "암호가 걸린 PDF는 읽을 수 없습니다. 암호를 해제한 파일을 올려 주세요.", 422)
        if doc.page_count > MAX_PAGES:
            raise PdfError("TOO_MANY_PAGES", f"{MAX_PAGES}쪽 이하의 PDF만 가능합니다.", 422)
        if doc.page_count == 0:
            raise PdfError("CORRUPT_PDF", "파일을 읽을 수 없습니다. 다른 파일을 올리거나 직접 작성해 주세요.", 422)
        return doc.page_count


@dataclass
class ParsedPdf:
    pages: list[str]  # 페이지별 원문 텍스트
    page_count: int
    used_ocr: bool
    sha256: str

    @property
    def text(self) -> str:
        return normalize_pages(self.pages)


# ── 추출 ──────────────────────────────────────────────────────────────────────
def extract_pages(data: bytes, *, ocr_fn=None) -> tuple[list[str], bool]:
    """(페이지별 텍스트, OCR 사용 여부). ocr_fn(png_bytes)->str 주입 가능(테스트·대체 엔진)."""
    texts: list[str] = []
    used_ocr = False
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            text = page.get_text("text", sort=True)
            if len(text.strip()) < MIN_PAGE_CHARS:  # 텍스트 레이어 없음 → 스캔본: 페이지를 200dpi 이미지로 OCR
                png = page.get_pixmap(dpi=200).tobytes("png")
                try:
                    text = (ocr_fn or ocr.ocr_png)(png)
                    used_ocr = True
                except ocr.OcrUnavailable:
                    text = text  # 빈 페이지일 수 있으므로 일단 유지, 전체가 비면 아래에서 오류
            texts.append(text)
    if not any(len(t.strip()) >= MIN_PAGE_CHARS for t in texts):
        raise PdfError("NO_TEXT", "PDF에서 텍스트를 읽을 수 없습니다. 직접 작성해 주세요.", 422)
    return texts, used_ocr


def parse_pdf(data: bytes, *, ocr_fn=None) -> ParsedPdf:
    pages, used_ocr = extract_pages(data, ocr_fn=ocr_fn)
    return ParsedPdf(pages, len(pages), used_ocr, hashlib.sha256(data).hexdigest())


def parse_pdf_isolated(data: bytes, timeout: float = PARSE_TIMEOUT_S) -> ParsedPdf:
    """별도 프로세스에서 파싱한다. 파서 크래시·무한루프가 API 프로세스에 영향을 주지 않는다 (TRD §8.3)."""
    try:
        proc = subprocess.run(
            # `-I`(격리 모드)는 cwd 를 sys.path 에 넣지 않아 app 모듈을 찾지 못한다. 대신 환경변수를 비워 비밀키·설정이 새지 않게 한다.
            [sys.executable, "-m", "app.ai.rag.pdf_worker"], input=data, capture_output=True, timeout=timeout,
            cwd=BACKEND_DIR, env={"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin"})
    except subprocess.TimeoutExpired as e:
        raise PdfError("PARSE_TIMEOUT", "파일 분석 시간이 초과되었습니다. 직접 작성해 주세요.", 422) from e
    try:
        out = json.loads(proc.stdout.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise PdfError("PARSE_FAILED", "파일을 읽을 수 없습니다. 다른 파일을 올리거나 직접 작성해 주세요.", 422) from e
    if "error" in out:
        err = out["error"]
        raise PdfError(err["code"], err["message"], err["http_status"])
    return ParsedPdf(out["pages"], out["page_count"], out["used_ocr"], hashlib.sha256(data).hexdigest())


# ── 정규화 ────────────────────────────────────────────────────────────────────
_PAGE_NO = re.compile(r"^\s*(?:[-–—]\s*)?(?:page\s*)?\d{1,3}\s*(?:/|of)?\s*\d{0,3}\s*(?:[-–—])?\s*$", re.IGNORECASE)


# 페이지 표기("1/3", "page 2 of 5", "- 2 -")만 정규화한다. 모든 숫자를 지우면 숫자만 다른 본문 줄이 머리글로 오인된다.
_PAGE_MARK = re.compile(r"(?:\d+\s*/\s*\d+|page\s*\d+(?:\s*of\s*\d+)?|[-–—]\s*\d+\s*[-–—])", re.IGNORECASE)


def _signature(line: str) -> str:
    return _PAGE_MARK.sub("#", unicodedata.normalize("NFC", line).strip().lower())


def normalize_pages(pages: list[str]) -> str:
    """NFC 정규화 · 연속 공백/개행 축소 · 머리글·바닥글·페이지 번호 제거 (TRD §3.1 전처리 규칙 1)."""
    per_page = [[unicodedata.normalize("NFC", ln).replace(" ", " ").rstrip() for ln in p.splitlines()] for p in pages]
    n = len(per_page)
    counter: Counter[str] = Counter()
    for lines in per_page:
        nonempty = [ln for ln in lines if ln.strip()]
        edge = {_signature(ln) for ln in nonempty[:2] + nonempty[-2:] if len(ln.strip()) <= 60}
        counter.update(edge)
    repeated = {sig for sig, c in counter.items() if n >= 2 and c >= max(2, math.ceil(n * 0.5))}

    cleaned_pages = []
    for lines in per_page:
        kept = [ln for ln in lines if not _PAGE_NO.match(ln) and _signature(ln) not in repeated]
        if not any(ln.strip() for ln in kept) and any(ln.strip() for ln in lines):
            kept = lines  # 페이지 전체가 "반복"으로 판정되면 머리글이 아니라 본문이 같은 것이므로 원문을 보존한다
        cleaned_pages.append("\n".join(kept))
    text = "\n\n".join(cleaned_pages)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── 섹션 분리 ─────────────────────────────────────────────────────────────────
SECTION_ALIASES = {
    "education": ["학력", "학력사항", "교육", "교육사항", "education"],
    "experience": ["경력", "경력사항", "근무경력", "직장경력", "experience", "work experience", "career"],
    "projects": ["프로젝트", "프로젝트경험", "프로젝트경력", "프로젝트이력", "프로젝트사항", "주요프로젝트", "개인프로젝트", "팀프로젝트", "수행프로젝트", "진행프로젝트",
                 "프로젝트및활동", "project", "projects", "project experience", "personal projects", "side projects", "selected projects"],
    "skills": ["기술", "기술스택", "보유기술", "스킬", "skills", "skill", "tech stack"],
    "certifications": ["자격", "자격증", "자격사항", "certification", "certifications", "license"],
    "self_intro": ["자기소개", "자기소개서", "지원동기", "성장과정", "자소서", "summary", "profile", "cover letter"],
}
_ALIAS_TO_KEY = {re.sub(r"\s+", "", a.lower()): key for key, aliases in SECTION_ALIASES.items() for a in aliases}
_HEADER_DECOR = re.compile(r"^[\s\[\]()<>■□●○◆◇▶▷★☆※#*=\-–—:·•\d.)]*|[\s\[\]()<>■□●○◆◇▶▷★☆※#*=\-–—:·•]*$")


def _header_key(line: str) -> str | None:
    if not line.strip() or len(line.strip()) > 25:
        return None
    core = re.sub(r"\s+", "", _HEADER_DECOR.sub("", line).lower())
    return _ALIAS_TO_KEY.get(core)


def split_sections(text: str) -> dict[str, str]:
    """섹션 헤더 사전 매칭으로 1차 분리. 첫 헤더 이전은 'profile'(성명·연락처 등), 같은 섹션이 반복되면 이어 붙인다."""
    sections: dict[str, list[str]] = {"profile": []}
    current = "profile"
    for line in text.splitlines():
        key = _header_key(line)
        if key:
            current = key
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}
