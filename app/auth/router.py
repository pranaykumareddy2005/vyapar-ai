"""Auth API - thin controllers delegating to AuthService."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.auth.dependencies import (
    Principal,
    get_auth_service,
    get_current_principal,
    get_user_repository,
    require_role,
)
from app.auth.repository import UserRepository
from app.auth.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenPair,
    UserCreate,
    UserOut,
)
from app.auth.service import AuthService
from app.common.exceptions import NotFoundError
from app.common.security import Role

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    service: AuthService = Depends(get_auth_service),
) -> RegisterResponse:
    user, tokens = service.register(payload)
    return RegisterResponse(
        user=UserOut.model_validate(user),
        business_id=user.business_id,
        tokens=tokens,
    )


@router.post("/login", response_model=TokenPair)
def login(
    payload: LoginRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenPair:
    return service.login(payload.email, payload.password)


@router.post("/refresh", response_model=TokenPair)
def refresh(
    payload: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenPair:
    return service.refresh(payload.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: LogoutRequest,
    service: AuthService = Depends(get_auth_service),
) -> None:
    service.logout(payload.refresh_token)


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    principal: Principal = Depends(require_role(Role.OWNER)),
    service: AuthService = Depends(get_auth_service),
) -> UserOut:
    user = service.create_user(principal.business_id, payload)
    return UserOut.model_validate(user)


@router.get("/users", response_model=list[UserOut])
def list_users(
    principal: Principal = Depends(require_role(Role.OWNER)),
    users: UserRepository = Depends(get_user_repository),
) -> list[UserOut]:
    return [UserOut.model_validate(u) for u in users.list_by_business(principal.business_id)]


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    principal: Principal = Depends(get_current_principal),
    users: UserRepository = Depends(get_user_repository),
) -> UserOut:
    # Tenant-scoped: a user id belonging to another business resolves to None
    # here and returns 404 (no cross-tenant read, no existence leak).
    user = users.get_in_business(user_id, principal.business_id)
    if user is None:
        raise NotFoundError("user not found")
    return UserOut.model_validate(user)
