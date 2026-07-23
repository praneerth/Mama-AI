"""
Request-local authenticated-principal context.

The middleware sets this context after validating a Bearer token. Legacy
helpers can then resolve the current account owner without changing every
existing route signature at once.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any


_current_principal: ContextVar[Any | None] = ContextVar(
    "mama_ai_current_principal",
    default=None,
)


def get_current_principal() -> Any | None:
    return _current_principal.get()


def set_current_principal(
    principal: Any,
) -> Token:
    return _current_principal.set(
        principal
    )


def reset_current_principal(
    token: Token,
) -> None:
    _current_principal.reset(
        token
    )


__all__ = [
    "get_current_principal",
    "reset_current_principal",
    "set_current_principal",
]
