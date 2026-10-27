"""인증 API: /auth/register, /auth/login, /auth/refresh, /auth/logout, /me (TRD §7.1)."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.core.security import create_token, hash_password
from app.models import Company, User
from app.models.enums import UserRole
from tests.conftest import API, TEST_JWT_SECRET

REG, LOGIN, REFRESH, LOGOUT, ME = (f"{API}/auth/register", f"{API}/auth/login", f"{API}/auth/refresh",
                                   f"{API}/auth/logout", f"{API}/me")


async def _register(client, payload):
    return await client.post(REG, json=payload)


# ── 회원가입 ────────────────────────────────────────────────────────────────
async def test_register_success_auto_login(client, register_payload):
    r = await _register(client, register_payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "hong@example.com"  # 소문자 정규화
    assert body["user"]["role"] == "applicant" and body["token_type"] == "bearer" and body["expires_in"] == 900
    assert r.headers["X-Request-Id"]
    # 생년월일·성별·연락처·비밀번호는 응답에 없어야 한다
    flat = r.text
    for secret in ("1995", "010-1234-5678", "Passw0rd!", "password"):
        assert secret not in flat
    # HttpOnly 쿠키 2개, refresh 는 인증 경로로 제한
    set_cookie = r.headers.get_list("set-cookie")
    access = next(c for c in set_cookie if c.startswith("access_token="))
    refresh = next(c for c in set_cookie if c.startswith("refresh_token="))
    assert "HttpOnly" in access and "HttpOnly" in refresh and "Path=/api/v1/auth" in refresh
    assert "samesite=lax" in access.lower()
    assert (await client.get(ME)).json()["email"] == "hong@example.com"  # 쿠키로 바로 인증됨


async def test_register_stores_hashed_password_and_encrypted_pii(client, session, register_payload):
    await _register(client, register_payload)
    row = (await session.execute(text("SELECT password_hash, name, phone, birth_date FROM users"))).one()
    assert row[0].startswith("$argon2id$")
    assert all(p not in " ".join(row) for p in ("Passw0rd!", "홍길동", "010-1234-5678", "1995-03-21"))
    user = (await session.execute(select(User))).scalar_one()
    assert (user.name, user.phone, user.birth_date, user.gender) == ("홍길동", "010-1234-5678", "1995-03-21", "male")
    assert user.role is UserRole.APPLICANT


@pytest.mark.parametrize("birth", ["1995/03/21", "1995-03-21"])
async def test_register_accepts_both_birth_formats(client, register_payload, birth):
    register_payload["birth_date"] = birth
    assert (await _register(client, register_payload)).status_code == 201


async def test_register_duplicate_email_case_insensitive(client, register_payload):
    assert (await _register(client, register_payload)).status_code == 201
    register_payload["email"] = "HONG@example.COM"
    r = await _register(client, register_payload)
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_ALREADY_EXISTS"
    assert r.json()["error"]["details"] == {"field": "email"}


@pytest.mark.parametrize("field,value,fragment", [
    ("email", "not-an-email", "이메일"),
    ("password", "short1!", "8"),
    ("password", "onlyletters!!", "영문, 숫자, 특수문자"),
    ("password", "NoSpecial123", "영문, 숫자, 특수문자"),
    ("password_confirm", "Different1!", "일치"),
    ("phone", "01012345678", "010-0000-0000"),
    ("birth_date", "2999/01/01", "생년월일"),
    ("birth_date", "19950321", ""),
    ("gender", "unknown", ""),
    ("name", "", ""),
])
async def test_register_validation_errors(client, register_payload, field, value, fragment):
    register_payload[field] = value
    r = await _register(client, register_payload)
    assert r.status_code == 422, r.text
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR" and err["request_id"]
    assert any(fragment in f["message"] for f in err["details"]["fields"])
    # 입력값(특히 비밀번호)을 응답에 되돌려주지 않는다
    assert register_payload["password"] not in r.text and "input" not in r.text


async def test_register_rejects_unknown_fields_and_role_escalation(client, register_payload):
    register_payload["role"] = "recruiter"  # 권한 상승 시도
    r = await _register(client, register_payload)
    assert r.status_code == 422


async def test_register_accepts_internal_domain_email(client, register_payload):
    register_payload["email"] = "kim@corp.local"
    assert (await _register(client, register_payload)).status_code == 201


# ── 로그인 ──────────────────────────────────────────────────────────────────
async def _login(client, email="hong@example.com", password="Passw0rd!", role="applicant"):
    return await client.post(LOGIN, json={"email": email, "password": password, "role": role})


async def test_login_success(client, register_payload):
    await _register(client, register_payload)
    client.cookies.clear()
    r = await _login(client, email="HONG@example.com")
    assert r.status_code == 200 and r.json()["user"]["role"] == "applicant"
    assert (await client.get(ME)).status_code == 200


async def test_login_failures_are_indistinguishable(client, register_payload):
    await _register(client, register_payload)
    wrong_pw = await _login(client, password="Wrong123!")
    no_user = await _login(client, email="nobody@example.com")
    wrong_role = await _login(client, role="recruiter")  # 지원자 계정으로 담당자 탭
    for r in (wrong_pw, no_user, wrong_role):
        assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"] == wrong_role.json()["error"]["message"]


async def test_login_inactive_account_reveals_only_after_valid_credentials(client, session, register_payload):
    await _register(client, register_payload)
    user = (await session.execute(select(User))).scalar_one()
    user.is_active = False
    await session.commit()
    assert (await _login(client, password="Wrong123!")).status_code == 401  # 자격 증명 불일치 시 사유 비노출
    r = await _login(client)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_recruiter_login_via_recruiter_tab(client, session):
    company = Company(name="다온커머스")
    session.add(company)
    await session.flush()
    session.add(User(email="hr@corp.local", password_hash=hash_password("Recruit1!"), role=UserRole.RECRUITER,
                     company_id=company.id, name="담당자"))
    await session.commit()
    ok = await _login(client, email="hr@corp.local", password="Recruit1!", role="recruiter")
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "recruiter"
    assert ok.json()["user"]["company_id"] == str(company.id)
    wrong_tab = await _login(client, email="hr@corp.local", password="Recruit1!", role="applicant")
    assert wrong_tab.status_code == 401


async def test_login_rate_limit_5_per_minute(client, register_payload):
    await _register(client, register_payload)
    codes = [(await _login(client, password="Wrong123!")).status_code for _ in range(5)]
    assert codes == [401] * 5
    r = await _login(client)  # 올바른 비밀번호여도 6번째 시도는 차단
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert int(r.headers["Retry-After"]) >= 1 and r.json()["error"]["details"]["retry_after_sec"] >= 1


# ── 토큰 / 보호된 리소스 ─────────────────────────────────────────────────────
async def test_me_requires_auth(client):
    r = await client.get(ME)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"
    assert r.headers["www-authenticate"] == "Bearer"


async def test_me_with_bearer_header(client, register_payload):
    token = (await _register(client, register_payload)).json()["access_token"]
    client.cookies.clear()
    assert (await client.get(ME, headers={"Authorization": f"Bearer {token}"})).status_code == 200
    assert (await client.get(ME, headers={"Authorization": "Bearer garbage"})).status_code == 401


async def test_me_rejects_expired_and_refresh_tokens(client, register_payload):
    user_id = uuid.UUID((await _register(client, register_payload)).json()["user"]["id"])
    client.cookies.clear()
    expired = create_token(TEST_JWT_SECRET, user_id, "applicant", "access", timedelta(seconds=-1))
    refresh_as_access = create_token(TEST_JWT_SECRET, user_id, "applicant", "refresh", timedelta(days=1))
    for t in (expired, refresh_as_access):
        assert (await client.get(ME, headers={"Authorization": f"Bearer {t}"})).status_code == 401


async def test_deleted_or_disabled_user_token_is_rejected(client, session, register_payload):
    token = (await _register(client, register_payload)).json()["access_token"]
    user = (await session.execute(select(User))).scalar_one()
    user.is_active = False
    await session.commit()
    client.cookies.clear()
    assert (await client.get(ME, headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_refresh_issues_new_tokens_and_rejects_access_token(client, register_payload):
    reg = await _register(client, register_payload)
    old_access = reg.json()["access_token"]
    r = await client.post(REFRESH)  # refresh 쿠키 자동 전송
    assert r.status_code == 200 and r.json()["access_token"] != old_access
    client.cookies.clear()  # access 토큰만으로는 refresh 불가
    r2 = await client.post(REFRESH, headers={"Authorization": f"Bearer {old_access}"})
    assert r2.status_code == 401
    client.cookies.set("refresh_token", old_access)  # access 토큰을 refresh 쿠키로 위장
    assert (await client.post(REFRESH)).status_code == 401


async def test_logout_clears_cookies(client, register_payload):
    await _register(client, register_payload)
    r = await client.post(LOGOUT)
    assert r.status_code == 204
    cleared = " ".join(r.headers.get_list("set-cookie"))
    assert "access_token=" in cleared and "refresh_token=" in cleared and "Max-Age=0" in cleared
    client.cookies.clear()
    assert (await client.post(LOGOUT)).status_code == 401  # TRD: 로그인 필요


async def test_error_format_for_unknown_route_and_method(client):
    r = await client.get(f"{API}/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    r = await client.get(LOGIN)
    assert r.status_code == 405 and r.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
