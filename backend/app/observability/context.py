"""Request-scoped observability context for Mama AI."""

from __future__ import annotations

from contextvars import ContextVar, Token


_request_id: ContextVar[str | None] = ContextVar(
    "mama_ai_request_id",
    default=None,
)


def get_request_id() -> str | None:
    """Return the current request correlation identifier."""

    return _request_id.get()


def set_request_id(request_id: str) -> Token:
    """Set the request correlation identifier for the current context."""

    return _request_id.set(request_id)


def reset_request_id(token: Token) -> None:
    """Restore the previous request correlation identifier."""

    _request_id.reset(token)


__all__ = [
    "get_request_id",
    "reset_request_id",
    "set_request_id",
]
