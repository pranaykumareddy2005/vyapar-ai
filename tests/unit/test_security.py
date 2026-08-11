from __future__ import annotations

import pytest
from app.common.exceptions import AuthenticationError
from app.common.security import (
    Role,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_secret,
    verify_secret,
)


def test_hash_and_verify_secret() -> None:
    hashed = hash_secret("s3cret-pin")
    assert hashed != "s3cret-pin"
    assert verify_secret("s3cret-pin", hashed)
    assert not verify_secret("wrong", hashed)


def test_access_token_roundtrip() -> None:
    token = create_access_token(user_id=7, business_id=3, role=Role.OWNER)
    claims = decode_token(token, expected_type="access")
    assert claims.user_id == 7
    assert claims.business_id == 3
    assert claims.role is Role.OWNER
    assert claims.token_type == "access"


def test_refresh_token_type_enforced() -> None:
    refresh = create_refresh_token(user_id=1, business_id=1, role=Role.EMPLOYEE)
    with pytest.raises(AuthenticationError, match="expected access token"):
        decode_token(refresh, expected_type="access")


def test_tampered_token_rejected() -> None:
    token = create_access_token(user_id=1, business_id=1, role=Role.ADMIN)
    with pytest.raises(AuthenticationError):
        decode_token(token + "x")
