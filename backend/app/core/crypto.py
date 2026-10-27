"""PII 컬럼 앱 레벨 암호화 (TRD §8.3: Fernet). SQLAlchemy TypeDecorator 로 투명하게 적용한다.

암호화 컬럼은 DB 에서 직접 검색·정렬할 수 없다 (이메일 등 검색 키는 평문 컬럼으로 둔다).
"""
from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

_fernet: Fernet | None = None


def init_crypto(key: str) -> None:
    """앱 기동 시 1회 호출 (create_app). 키는 로그에 남기지 않는다."""
    global _fernet
    _fernet = Fernet(key.encode())


def _f() -> Fernet:
    if _fernet is None:
        raise RuntimeError("암호화가 초기화되지 않았습니다 (init_crypto 미호출)")
    return _fernet


def encrypt_str(value: str) -> str:
    return _f().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_str(token: str) -> str:
    return _f().decrypt(token.encode("ascii")).decode("utf-8")


class EncryptedText(TypeDecorator):
    """문자열을 Fernet 으로 암호화하여 TEXT 로 저장."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else encrypt_str(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return None if value is None else decrypt_str(value)


class EncryptedJSON(TypeDecorator):
    """JSON 직렬화 후 Fernet 암호화하여 TEXT 로 저장 (이력서 데이터 등 PII 포함 구조)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        return None if value is None else encrypt_str(json.dumps(value, ensure_ascii=False))

    def process_result_value(self, value: str | None, dialect: Any) -> Any:
        return None if value is None else json.loads(decrypt_str(value))
