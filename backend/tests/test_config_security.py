"""설정 검증(기동 거부), 비밀번호 해시, JWT, 레이트 리미터, 암호화."""
from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core import crypto
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_token, decode_token, hash_password, verify_password
from tests.conftest import TEST_FERNET_KEY, TEST_JWT_SECRET

SECRET = TEST_JWT_SECRET


def test_settings_require_secrets(monkeypatch):
    monkeypatch.delenv("JWT_SECRET")
    monkeypatch.delenv("DATA_ENCRYPTION_KEY")
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None, data_encryption_key=TEST_FERNET_KEY)  # jwt_secret 누락 → 기동 거부
    with pytest.raises(ValidationError, match="data_encryption_key"):
        Settings(_env_file=None, jwt_secret=SECRET)  # data_encryption_key 누락 → 기동 거부


def test_settings_reject_weak_values():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret="short", data_encryption_key=TEST_FERNET_KEY)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jwt_secret=SECRET, data_encryption_key="not-a-fernet-key")


def test_settings_origins_parse():
    s = Settings(_env_file=None, jwt_secret=SECRET, data_encryption_key=TEST_FERNET_KEY,
                 allowed_origins="https://a.corp.local, https://b.corp.local")
    assert s.origins == ["https://a.corp.local", "https://b.corp.local"]


def test_password_hash_is_argon2id_and_verifies():
    h = hash_password("Passw0rd!")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "Passw0rd!")
    assert not verify_password(h, "wrong")
    assert not verify_password(None, "anything")  # 존재하지 않는 계정


def test_token_roundtrip_and_type_check():
    uid = uuid.uuid4()
    access = create_token(SECRET, uid, "applicant", "access", timedelta(minutes=15))
    claims = decode_token(SECRET, access, "access")
    assert claims.user_id == uid and claims.role == "applicant"
    with pytest.raises(ApiError) as e:
        decode_token(SECRET, access, "refresh")  # access 토큰을 refresh 로 사용 불가
    assert e.value.status_code == 401


def test_token_rejects_expired_tampered_and_alg_none():
    uid = uuid.uuid4()
    expired = create_token(SECRET, uid, "applicant", "access", timedelta(seconds=-5))
    for bad in (expired, create_token("other-secret-" + "y" * 40, uid, "applicant", "access", timedelta(minutes=1)),
                jwt.encode({"sub": str(uid), "type": "access"}, key="", algorithm="none"), "garbage"):
        with pytest.raises(ApiError):
            decode_token(SECRET, bad, "access")


def test_rate_limiter_window():
    now = [0.0]
    lim = SlidingWindowLimiter(3, 60, clock=lambda: now[0])
    assert [lim.hit("k")[0] for _ in range(3)] == [True, True, True]
    ok, retry = lim.hit("k")
    assert not ok and 1 <= retry <= 61
    assert lim.hit("other")[0]  # 키별 독립
    now[0] = 61.0
    assert lim.hit("k")[0]  # 윈도 경과 후 허용


def test_crypto_roundtrip_and_wrong_key_fails():
    crypto.init_crypto(TEST_FERNET_KEY)
    token = crypto.encrypt_str("민감정보")
    assert "민감정보" not in token and crypto.decrypt_str(token) == "민감정보"
    crypto.init_crypto(Fernet.generate_key().decode())
    with pytest.raises(Exception):
        crypto.decrypt_str(token)
    crypto.init_crypto(TEST_FERNET_KEY)  # 복원
