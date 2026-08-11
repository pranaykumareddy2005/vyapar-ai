"""Authentication flow + security cases (SRS security test checklist 1-6, 12-14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from app.auth.models import User
from app.config import get_settings
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.helpers import auth_header, register_business


def test_register_returns_tokens_and_no_secrets(api: TestClient) -> None:
    reg = register_business(api)
    assert reg.access and reg.refresh
    # #12 - response must not leak password hash.
    resp = api.get(f"/api/auth/users/{reg.user_id}", headers=auth_header(reg.access))
    body = resp.json()
    assert "password_hash" not in body
    assert "password" not in body


def test_valid_login(api: TestClient) -> None:  # #1
    register_business(api, email="a@shop.co", password="correcthorse1")
    resp = api.post("/api/auth/login", json={"email": "a@shop.co", "password": "correcthorse1"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_invalid_password(api: TestClient) -> None:  # #2
    register_business(api, email="b@shop.co", password="correcthorse1")
    resp = api.post("/api/auth/login", json={"email": "b@shop.co", "password": "wrongpass1"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "authentication_error"


def test_unknown_user_login(api: TestClient) -> None:
    resp = api.post("/api/auth/login", json={"email": "nobody@shop.co", "password": "whatever12"})
    assert resp.status_code == 401


def _expired_access_token(user_id: int, business_id: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "biz": business_id,
        "role": "OWNER",
        "type": "access",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def test_expired_access_token_rejected(api: TestClient) -> None:  # #3
    reg = register_business(api)
    token = _expired_access_token(reg.user_id, reg.business_id)
    resp = api.get("/api/business/me", headers=auth_header(token))
    assert resp.status_code == 401


def test_invalid_token_rejected(api: TestClient) -> None:  # #4
    resp = api.get("/api/business/me", headers=auth_header("not-a-jwt"))
    assert resp.status_code == 401


def test_missing_token_rejected(api: TestClient) -> None:
    resp = api.get("/api/business/me")
    assert resp.status_code == 401


def test_refresh_rotates_and_revokes_old(api: TestClient) -> None:  # #5
    reg = register_business(api)
    resp = api.post("/api/auth/refresh", json={"refresh_token": reg.refresh})
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert new_tokens["access_token"]
    # Old refresh token is now revoked (rotation).
    replay = api.post("/api/auth/refresh", json={"refresh_token": reg.refresh})
    assert replay.status_code == 401


def test_logout_revokes_refresh_token(api: TestClient) -> None:  # #5
    reg = register_business(api)
    out = api.post("/api/auth/logout", json={"refresh_token": reg.refresh})
    assert out.status_code == 204
    resp = api.post("/api/auth/refresh", json={"refresh_token": reg.refresh})
    assert resp.status_code == 401


def test_access_token_not_accepted_as_refresh(api: TestClient) -> None:
    reg = register_business(api)
    resp = api.post("/api/auth/refresh", json={"refresh_token": reg.access})
    assert resp.status_code == 401


def test_inactive_user_blocked(api: TestClient, db_session: Session) -> None:  # #14
    reg = register_business(api)
    user = db_session.get(User, reg.user_id)
    assert user is not None
    user.is_active = False
    db_session.commit()
    resp = api.get("/api/business/me", headers=auth_header(reg.access))
    assert resp.status_code == 401
