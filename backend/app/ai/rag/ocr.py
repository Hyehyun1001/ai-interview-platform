"""스캔본 PDF 용 OCR: 페이지 이미지를 Tesseract(kor+eng) 서브프로세스로 처리 (TRD §3.1, §2.1: 구간 처리 후 즉시 종료)."""
from __future__ import annotations

import shutil
import subprocess

OCR_TIMEOUT_S = 30


class OcrUnavailable(Exception):
    """tesseract 미설치 또는 실행 실패."""


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_png(png: bytes, *, lang: str = "kor+eng", timeout: float = OCR_TIMEOUT_S) -> str:
    exe = shutil.which("tesseract")
    if exe is None:
        raise OcrUnavailable("tesseract 가 설치되어 있지 않습니다 (brew install tesseract tesseract-lang)")
    try:
        proc = subprocess.run([exe, "stdin", "stdout", "-l", lang], input=png, capture_output=True, timeout=timeout, check=True)
    except (subprocess.SubprocessError, OSError) as e:
        raise OcrUnavailable(f"OCR 실행 실패: {type(e).__name__}") from e
    return proc.stdout.decode("utf-8", errors="replace")
