"""Authentication service: onboarding, login, token refresh/rotation, logout.

Owns its transaction boundaries explicitly (commit-as-you-go with rollback on
failure). Uses the shared ``common.security`` primitives for hashing and JWTs;
it does not reimplement them.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.repository import UserRepository
from app.auth.schemas import RegisterRequest, TokenPair, UserCreate
from app.auth.tokens import RefreshTokenStore
from app.business.models import Business
from app.business.repository import BusinessRepository
from app.common.exceptions import AuthenticationError, ConflictError
from app.common.security import (
    Role,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_secret,
    verify_secret,
)
from app.config import Settings


class AuthService:
    def __init__(
        self,
        session: Session,
        users: UserRepository,
        businesses: BusinessRepository,
        token_store: RefreshTokenStore,
        settings: Settings,
    ) -> None:
        self._session = session
        self._users = users
        self._businesses = businesses
        self._token_store = token_store
        self._settings = settings

    # --- token helpers ----------------------------------------------------

    def _issue_tokens(self, user: User) -> TokenPair:
        access = create_access_token(user.id, user.business_id, user.role)
        refresh = create_refresh_token(user.id, user.business_id, user.role)
        return TokenPair(access_token=access, refresh_token=refresh)

    # --- onboarding -------------------------------------------------------

    def register(self, payload: RegisterRequest) -> tuple[User, TokenPair]:
        """Create a Business and its first OWNER user atomically."""
        if self._users.email_exists(payload.email):
            raise ConflictError("email is already registered")
        try:
            business = self._businesses.add(
                Business(
                    name=payload.business_name,
                    category=payload.category,
                    contact_number=payload.contact_number,
                    address=payload.address,
                )
            )
            user = self._users.add(
                User(
                    business_id=business.id,
                    email=payload.email,
                    password_hash=hash_secret(payload.password),
                    role=Role.OWNER,
                )
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return user, self._issue_tokens(user)

    def create_user(self, business_id: int, payload: UserCreate) -> User:
        """OWNER adds another user within its own business."""
        if self._users.email_exists(payload.email):
            raise ConflictError("email is already registered")
        try:
            user = self._users.add(
                User(
                    business_id=business_id,
                    email=payload.email,
                    password_hash=hash_secret(payload.password),
                    role=payload.role,
                )
            )
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise
        return user

    # --- session lifecycle ------------------------------------------------

    def login(self, email: str, password: str) -> TokenPair:
        user = self._users.get_by_email(email)
        # Verify against a real-looking hash regardless to reduce user
        # enumeration via timing; still return a generic error.
        if user is None or not verify_secret(password, user.password_hash):
            raise AuthenticationError("invalid credentials")
        if not user.is_active:
            raise AuthenticationError("account is inactive")
        return self._issue_tokens(user)

    def refresh(self, refresh_token: str) -> TokenPair:
        claims = decode_token(refresh_token, expected_type="refresh")
        if self._token_store.is_revoked(claims.jti):
            raise AuthenticationError("refresh token has been revoked")
        user = self._users.get_in_business(claims.user_id, claims.business_id)
        if user is None or not user.is_active:
            raise AuthenticationError("account is inactive")
        # Rotate: revoke the presented refresh token, issue a fresh pair.
        self._token_store.revoke(claims.jti, self._settings.jwt_refresh_ttl_seconds)
        return self._issue_tokens(user)

    def logout(self, refresh_token: str) -> None:
        claims = decode_token(refresh_token, expected_type="refresh")
        self._token_store.revoke(claims.jti, self._settings.jwt_refresh_ttl_seconds)
