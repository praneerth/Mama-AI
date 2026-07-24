"""Request-owner-scoped in-memory conversation history."""

from __future__ import annotations

from threading import RLock

from app.core.principal_context import get_current_principal


_DEFAULT_OWNER_ID = "local-user"
_histories: dict[str, list[dict[str, str]]] = {}
_lock = RLock()


def _resolve_owner(owner_id: str | None = None) -> str:
    if owner_id is None:
        principal = get_current_principal()
        candidate = getattr(principal, "owner_id", None)
        owner_id = candidate if isinstance(candidate, str) else _DEFAULT_OWNER_ID

    if not isinstance(owner_id, str):
        raise TypeError("Owner ID must be text.")

    owner_id = owner_id.strip()

    if not owner_id:
        raise ValueError("Owner ID cannot be empty.")

    return owner_id


def add_message(role: str, text: str, *, owner_id: str | None = None):
    owner_id = _resolve_owner(owner_id)
    message = {"role": role, "text": text}

    with _lock:
        _histories.setdefault(owner_id, []).append(message)


def get_history(*, owner_id: str | None = None):
    owner_id = _resolve_owner(owner_id)

    with _lock:
        return [dict(item) for item in _histories.get(owner_id, [])]


def clear_history(*, owner_id: str | None = None):
    owner_id = _resolve_owner(owner_id)

    with _lock:
        history = _histories.get(owner_id)

        if history is not None:
            history.clear()

        if owner_id != _DEFAULT_OWNER_ID:
            _histories.pop(owner_id, None)


# Backward-compatible module-level alias for legacy imports that only inspect it.
conversation_history = _histories.setdefault(_DEFAULT_OWNER_ID, [])
