"""Maps DomainError instances to JSON HTTP responses at the app boundary."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.common.exceptions import DomainError


async def _domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    # Registered only for DomainError; the guard narrows the type without
    # relying on `assert` (which is stripped under `python -O`).
    if not isinstance(exc, DomainError):
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "internal error"}},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
