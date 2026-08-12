"""Base security infrastructure: password/PIN hashing and JWT tokens.

RBAC dependencies (``require_role``, ``require_pin``) that need request context
live in the ``auth`` module; this module provides the pure, framework-agnostic
primitives they build on.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.common.exceptions import AuthenticationError
from app.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh"]


class Role(enum.StrEnum):
    """RBAC roles per SDD (§8)."""

    OWNER = "OWNER"
    EMPLOYEE = "EMPLOYEE"
    ADMIN = "ADMIN"


# --- Password / PIN hashing ------------------------------------------------


def hash_secret(raw: str) -> str:
    """Hash a password or Business PIN with bcrypt."""
    return _pwd_context.hash(raw)


def verify_secret(raw: str, hashed: str) -> bool:
    """Constant-time verification of a password or PIN against its hash."""
    return _pwd_context.verify(raw, hashed)


# --- JWT -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Decoded, validated identity carried by a JWT."""

    user_id: int
    business_id: int
    role: Role
    token_type: TokenType
    jti: str


def _create_token(
    *,
    user_id: int,
    business_id: int,
    role: Role,
    token_type: TokenType,
    ttl_seconds: int,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "biz": business_id,
        "role": role.value,
        "type": token_type,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, business_id: int, role: Role) -> str:
    settings = get_settings()
    return _create_token(
        user_id=user_id,
        business_id=business_id,
        role=role,
        token_type="access",  # nosec B106
        ttl_seconds=settings.jwt_access_ttl_seconds,
    )


def create_refresh_token(user_id: int, business_id: int, role: Role) -> str:
    settings = get_settings()
    return _create_token(
        user_id=user_id,
        business_id=business_id,
        role=role,
        token_type="refresh",  # nosec B106
        ttl_seconds=settings.jwt_refresh_ttl_seconds,
    )


def decode_token(token: str, *, expected_type: TokenType | None = None) -> TokenClaims:
    """Decode and validate a JWT, returning its claims.

    Raises :class:`AuthenticationError` on any signature/expiry/shape problem.
    """
    settings = get_settings()
    try:
        raw = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthenticationError("invalid or expired token") from exc

    token_type: str = raw.get("type", "")
    if expected_type is not None and token_type != expected_type:
        raise AuthenticationError(f"expected {expected_type} token")

    try:
        return TokenClaims(
            user_id=int(raw["sub"]),
            business_id=int(raw["biz"]),
            role=Role(raw["role"]),
            token_type=token_type,  # type: ignore[arg-type]
            jti=str(raw["jti"]),
        )
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("malformed token claims") from exc
