"""이력서 PDF 검증 · 추출 · 정규화 · 섹션 분리 · 격리 파싱 (TRD §3.1, RAG-1/2)."""
from __future__ import annotations

import subprocess

import pytest

from app.ai.rag import ocr, pdf_parser
from app.ai.rag.pdf_parser import (MAX_PAGES, MAX_PDF_BYTES, PdfError, normalize_pages, parse_pdf, parse_pdf_isolated,
                                   split_sections, validate_pdf_upload)
from tests.pdf_factory import RESUME_TEXT, make_pdf, make_scanned_pdf, merge


# ── 업로드 검증 (RAG-1) ──────────────────────────────────────────────────────
def test_validate_accepts_pdf_and_returns_page_count():
    assert validate_pdf_upload("이력서.pdf", "application/pdf", make_pdf(["a" * 30, "b" * 30])) == 2
    assert validate_pdf_upload("R.PDF", "application/pdf; charset=binary", make_pdf(["x" * 30])) == 1


@pytest.mark.parametrize("filename,ctype,data", [
    ("resume.docx", "application/pdf", b"%PDF-1.4 x"), ("resume.hwp", "application/pdf", b"%PDF-1.4 x"),
    ("resume.png", "image/png", b"\x89PNG"), ("resume.pdf", "text/plain", b"%PDF-1.4 x"),
    ("resume.pdf", None, b"%PDF-1.4 x"), ("resume.pdf", "application/pdf", b"PK\x03\x04 docx disguised as pdf"),
    ("resume.pdf", "application/pdf", b"")])
def test_validate_rejects_non_pdf_with_user_message(filename, ctype, data):
    with pytest.raises(PdfError) as e:
        validate_pdf_upload(filename, ctype, data)
    assert (e.value.code, e.value.http_status, e.value.message) == ("UNSUPPORTED_MEDIA_TYPE", 415, "PDF 파일만 업로드할 수 있습니다.")


def test_validate_rejects_too_large_too_many_pages_encrypted_and_corrupt():
    with pytest.raises(PdfError) as e:
        validate_pdf_upload("a.pdf", "application/pdf", b"%PDF-" + b"0" * MAX_PDF_BYTES)
    assert (e.value.code, e.value.http_status) == ("PAYLOAD_TOO_LARGE", 413)
    with pytest.raises(PdfError) as e:
        validate_pdf_upload("a.pdf", "application/pdf", make_pdf(["p" * 30] * (MAX_PAGES + 1)))
    assert e.value.code == "TOO_MANY_PAGES" and "20쪽" in e.value.message
    with pytest.raises(PdfError) as e:
        validate_pdf_upload("a.pdf", "application/pdf", make_pdf(["secret" * 10], password="pw"))
    assert e.value.code == "ENCRYPTED_PDF"
    with pytest.raises(PdfError) as e:
        validate_pdf_upload("a.pdf", "application/pdf", b"%PDF-1.4\nthis is not a real pdf")
    assert (e.value.code, e.value.http_status) == ("CORRUPT_PDF", 422)
    assert validate_pdf_upload("a.pdf", "application/pdf", make_pdf(["p" * 30] * MAX_PAGES)) == MAX_PAGES  # 경계값 20쪽은 허용


# ── 추출 ─────────────────────────────────────────────────────────────────────
def test_extract_text_layer_without_ocr_and_sha256():
    data = make_pdf([RESUME_TEXT])
    called = []
    parsed = parse_pdf(data, ocr_fn=lambda png: called.append(1) or "")
    assert not called and not parsed.used_ocr and parsed.page_count == 1  # 가벼운 경로 우선: 텍스트 레이어면 OCR 을 쓰지 않는다
    assert "다온커머스" in parsed.text and len(parsed.sha256) == 64


def test_scanned_page_goes_through_ocr_at_200dpi_png():
    seen = []

    def fake_ocr(png: bytes) -> str:
        seen.append(png[:8])
        return "OCR 로 읽은 이력서 본문입니다. 김지원 한빛대학교 졸업"

    parsed = parse_pdf(make_scanned_pdf(2), ocr_fn=fake_ocr)
    assert parsed.used_ocr and len(seen) == 2 and seen[0] == b"\x89PNG\r\n\x1a\n" and "한빛대학교" in parsed.text


def test_mixed_pdf_runs_ocr_only_for_pages_without_text_layer():
    calls = []
    data = merge(make_pdf(["텍스트 레이어가 있는 첫 페이지입니다. 충분히 긴 문장."]), make_scanned_pdf(1))
    parsed = parse_pdf(data, ocr_fn=lambda png: calls.append(1) or "스캔된 두 번째 페이지의 OCR 결과 텍스트입니다")
    assert len(calls) == 1 and parsed.used_ocr and "첫 페이지" in parsed.text and "두 번째 페이지" in parsed.text


def test_scanned_pdf_without_tesseract_raises_user_facing_error(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _name: None)
    with pytest.raises(PdfError) as e:
        parse_pdf(make_scanned_pdf(1))
    assert e.value.code == "NO_TEXT" and "직접 작성" in e.value.message


def test_ocr_png_reports_unavailable_without_binary(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _name: None)
    assert not ocr.tesseract_available()
    with pytest.raises(ocr.OcrUnavailable):
        ocr.ocr_png(b"x")


# ── 격리 프로세스 파싱 (TRD §8.3) ────────────────────────────────────────────
def test_isolated_parse_returns_same_result_as_inprocess():
    data = make_pdf([RESUME_TEXT])
    iso, local = parse_pdf_isolated(data), parse_pdf(data)
    assert iso.pages == local.pages and iso.page_count == 1 and iso.sha256 == local.sha256


def test_isolated_parse_maps_worker_errors_to_pdf_error():
    with pytest.raises(PdfError) as e:
        parse_pdf_isolated(make_pdf(["secret" * 10], password="pw"))
    assert e.value.code == "ENCRYPTED_PDF"
    with pytest.raises(PdfError) as e:
        parse_pdf_isolated(b"not a pdf at all")
    assert e.value.code == "UNSUPPORTED_MEDIA_TYPE"


def test_isolated_parse_timeout_and_garbage_output(monkeypatch):
    def timeout(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise subprocess.TimeoutExpired("worker", 30)

    monkeypatch.setattr(pdf_parser.subprocess, "run", timeout)
    with pytest.raises(PdfError) as e:
        parse_pdf_isolated(b"%PDF-")
    assert e.value.code == "PARSE_TIMEOUT"

    monkeypatch.setattr(pdf_parser.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, b"\xff garbage", b""))
    with pytest.raises(PdfError) as e:
        parse_pdf_isolated(b"%PDF-")
    assert e.value.code == "PARSE_FAILED"


# ── 정규화 ───────────────────────────────────────────────────────────────────
def test_normalize_removes_repeated_header_footer_and_page_numbers():
    pages = [f"(주)다온 지원서 - 대외비\n본문 {i} 줄 하나\n본문 {i} 줄 둘\n- {i} -\n김지원 이력서" for i in range(1, 4)]
    text = normalize_pages(pages)
    assert "대외비" not in text and "김지원 이력서" not in text and "- 1 -" not in text
    assert "본문 1 줄 하나" in text and "본문 3 줄 둘" in text


def test_normalize_removes_footer_with_page_marker_but_keeps_body_lines_differing_only_by_digits():
    pages = [f"1. 항목 {i} 설명\n2. 항목 {i} 상세\n김지원 이력서 {i}/3" for i in range(1, 4)]
    text = normalize_pages(pages)
    assert "이력서" not in text  # "n/3" 페이지 표기가 있는 반복 바닥글은 제거
    assert all(f"항목 {i} 설명" in text and f"항목 {i} 상세" in text for i in range(1, 4))  # 숫자만 다른 본문 줄은 보존


def test_normalize_never_empties_a_page_made_only_of_repeated_lines():
    assert normalize_pages(["동일한 한 줄 본문", "동일한 한 줄 본문"]).count("동일한 한 줄 본문") == 2


def test_normalize_keeps_single_page_edges_collapses_whitespace_and_applies_nfc():
    text = normalize_pages(["첫 줄  공백   많음\n\n\n\n\n다음 문단\n1"])
    assert "공백 많음" in text and "\n\n\n" not in text
    import unicodedata

    assert normalize_pages([unicodedata.normalize("NFD", "한글 정규화 테스트")]) == "한글 정규화 테스트"
    assert "첫 줄" in text  # 한 페이지짜리 문서는 가장자리 줄을 머리글로 오인해 지우지 않는다


# ── 섹션 분리 ────────────────────────────────────────────────────────────────
def test_split_sections_on_plain_headers():
    s = split_sections(RESUME_TEXT)
    assert set(s) == {"profile", "education", "experience", "projects", "skills", "certifications", "self_intro"}
    assert "김지원" in s["profile"] and "한빛대학교" in s["education"] and "Redis 캐시" in s["experience"]
    assert "Spring Boot" in s["projects"] and s["certifications"] == "정보처리기사" and "수치로" in s["self_intro"]


@pytest.mark.parametrize("header,key", [
    ("[ 경력 사항 ]", "experience"), ("■ 학력", "education"), ("2. 프로젝트", "projects"), ("Experience", "experience"),
    ("EDUCATION", "education"), ("【기술 스택】", None), ("기술 스택", "skills"), ("자격증", "certifications"), ("지원동기", "self_intro"),
    ("- Skills -", "skills")])
def test_split_sections_recognizes_decorated_and_english_headers(header, key):
    s = split_sections(f"홍길동\n{header}\n내용 한 줄입니다\n")
    if key:
        assert s[key] == "내용 한 줄입니다"
    assert "홍길동" in s["profile"]


def test_split_sections_ignores_headers_inside_sentences_and_merges_repeats():
    s = split_sections("이름\n경력\n회사 A\n경력을 쌓기 위해 지원했습니다\n프로젝트\nP1\n경력\n회사 B\n")
    assert "경력을 쌓기 위해" in s["experience"]  # 문장 속 단어는 헤더가 아니다
    assert s["experience"].splitlines()[-1] == "회사 B" and "회사 A" in s["experience"]  # 반복된 헤더는 이어 붙인다
