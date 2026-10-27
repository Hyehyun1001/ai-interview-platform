"""테스트용 PDF 생성 (PyMuPDF 내장 한글 폰트). 외부 샘플 파일에 의존하지 않는다."""
from __future__ import annotations

import pymupdf


def make_pdf(pages: list[str], *, password: str | None = None) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 555, 800), text, fontname="korea", fontsize=10)
    if password:
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password + "-owner")
    return doc.tobytes()


def make_scanned_pdf(n_pages: int = 1) -> bytes:
    """텍스트 레이어가 없는 이미지 전용 PDF (스캔본)."""
    src = pymupdf.open()
    p = src.new_page()
    p.draw_rect(pymupdf.Rect(50, 50, 300, 120), fill=(0.6, 0.6, 0.6))
    png = p.get_pixmap(dpi=60).tobytes("png")
    out = pymupdf.open()
    for _ in range(n_pages):
        page = out.new_page()
        page.insert_image(page.rect, stream=png)
    return out.tobytes()


def merge(*pdfs: bytes) -> bytes:
    out = pymupdf.open()
    for data in pdfs:
        out.insert_pdf(pymupdf.open(stream=data, filetype="pdf"))
    return out.tobytes()


RESUME_TEXT = """김지원
010-1234-5678 / jiwon@example.com

학력
한빛대학교 컴퓨터공학 학사 2018.03 ~ 2022.02

경력
(주)다온커머스 백엔드 개발자 2022.03 ~ 현재
주문·결제 API 개발, Redis 캐시 도입으로 조회 응답 시간 개선

프로젝트
주문 조회 성능 개선 (2023.04 ~ 2023.09)
Spring Boot, Redis, MySQL 로 응답 800ms 를 200ms 로 단축

기술
Java, Spring Boot, Redis, MySQL

자격
정보처리기사

자기소개
문제의 원인을 수치로 확인하고 개선 결과를 검증하는 방식으로 일합니다.
"""
