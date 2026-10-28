"""Domain errors. Services raise these; the desktop screens show them to the user.

Messages are written for end users: they never contain stack traces, SQL, or
internal identifiers beyond what the caller already supplied.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, fields: dict[str, str] | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}
        self.details = details or {}


class ValidationFailed(DomainError):
    status_code = 422
    code = "validation_failed"


class AuthenticationRequired(DomainError):
    status_code = 401
    code = "authentication_required"

    def __init__(self, message: str = "Please sign in to continue.") -> None:
        super().__init__(message)


class PermissionDenied(DomainError):
    status_code = 403
    code = "permission_denied"

    def __init__(self, message: str = "You do not have permission to do that.") -> None:
        super().__init__(message)


class NotFound(DomainError):
    """Also used for records outside the caller's organization or visibility (no existence leak)."""

    status_code = 404
    code = "not_found"

    def __init__(self, message: str = "The requested record was not found.") -> None:
        super().__init__(message)


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class RateLimited(DomainError):
    status_code = 429
    code = "rate_limited"
