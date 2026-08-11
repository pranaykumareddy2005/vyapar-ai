"""Domain exception hierarchy.

Services raise these; the API layer maps them to HTTP responses (see
:mod:`app.common.error_handlers`). Domain code stays free of HTTP concerns.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for all expected, business-level errors."""

    status_code: int = 400
    code: str = "domain_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ValidationError(DomainError):
    status_code = 422
    code = "validation_error"


class AuthenticationError(DomainError):
    status_code = 401
    code = "authentication_error"


class AuthorizationError(DomainError):
    status_code = 403
    code = "authorization_error"


class TenantIsolationError(AuthorizationError):
    """Raised when a request touches a record outside its own business."""

    code = "tenant_isolation_error"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class InsufficientStockError(ConflictError):
    code = "insufficient_stock"
