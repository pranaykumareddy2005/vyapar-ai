"""FastAPI dependencies for authentication, RBAC, and PIN step-up.

These are the single choke-points the routers use; authorization is enforced
here at the API boundary, never assumed from the client.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.repository import UserRepository
from app.auth.service import AuthService
from app.auth.tokens import RefreshTokenStore
from app.business.repository import BusinessRepository
from app.business.service import BusinessService
from app.common.exceptions import AuthenticationError, AuthorizationError
from app.common.security import Role, decode_token
from app.config import Settings, get_settings
from app.db import get_session
from app.providers import get_refresh_token_store

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller's identity and tenant context."""

    user_id: int
    business_id: int
    role: Role


# --- repository / service wiring --------------------------------------------


def get_user_repository(session: Session = Depends(get_session)) -> UserRepository:
    return UserRepository(session)


def get_business_repository(session: Session = Depends(get_session)) -> BusinessRepository:
    return BusinessRepository(session)


def get_auth_service(
    session: Session = Depends(get_session),
    users: UserRepository = Depends(get_user_repository),
    businesses: BusinessRepository = Depends(get_business_repository),
    token_store: RefreshTokenStore = Depends(get_refresh_token_store),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(session, users, businesses, token_store, settings)


def get_business_service(
    session: Session = Depends(get_session),
    businesses: BusinessRepository = Depends(get_business_repository),
) -> BusinessService:
    return BusinessService(session, businesses)


# --- authentication ---------------------------------------------------------


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    users: UserRepository = Depends(get_user_repository),
) -> Principal:
    """Validate the access token and load the (active) user behind it."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError("missing bearer token")

    claims = decode_token(credentials.credentials, expected_type="access")
    # Re-check the user against the DB so a deactivated user cannot keep acting
    # on a still-valid access token.
    user = users.get_in_business(claims.user_id, claims.business_id)
    if user is None or not user.is_active:
        raise AuthenticationError("user is inactive or no longer exists")
    return Principal(user_id=user.id, business_id=user.business_id, role=user.role)


def require_role(*allowed: Role) -> Callable[[Principal], Principal]:
    """Dependency factory enforcing that the caller holds one of ``allowed``."""

    def _dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in allowed:
            raise AuthorizationError("insufficient role for this operation")
        return principal

    return _dependency


def require_pin(
    principal: Principal = Depends(get_current_principal),
    x_business_pin: str | None = Header(default=None, alias="X-Business-PIN"),
    business_service: BusinessService = Depends(get_business_service),
) -> Principal:
    """Business PIN step-up for sensitive actions (FR-AUTH-03).

    The PIN is read from the ``X-Business-PIN`` header, verified against the
    caller's own business, and never logged or echoed.
    """
    if not x_business_pin:
        raise AuthorizationError("business PIN required for this action")
    if not business_service.verify_pin(principal.business_id, x_business_pin):
        raise AuthorizationError("invalid business PIN")
    return principal
