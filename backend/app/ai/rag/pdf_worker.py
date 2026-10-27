"""PDF 파싱 워커: stdin 으로 PDF 바이트를 받아 stdout 으로 JSON 을 출력한다 (격리 프로세스, parse_pdf_isolated 가 호출)."""
from __future__ import annotations

import json
import sys

from app.ai.rag.pdf_parser import PdfError, parse_pdf, validate_pdf_upload


def main() -> int:
    data = sys.stdin.buffer.read()
    try:
        validate_pdf_upload("resume.pdf", "application/pdf", data)  # 매직바이트·크기·쪽수·암호 재검증 (방어 심층)
        parsed = parse_pdf(data)
        out = {"pages": parsed.pages, "page_count": parsed.page_count, "used_ocr": parsed.used_ocr}
    except PdfError as e:
        out = {"error": {"code": e.code, "message": e.message, "http_status": e.http_status}}
    except Exception:  # noqa: BLE001  내부 오류 상세는 노출하지 않는다
        out = {"error": {"code": "PARSE_FAILED", "message": "파일을 읽을 수 없습니다. 다른 파일을 올리거나 직접 작성해 주세요.", "http_status": 422}}
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
