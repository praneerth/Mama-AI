"""
Thread-safe event system for Mama AI.

Components can publish and subscribe to events without creating
direct dependencies between modules.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from uuid import uuid4

from app.core.task import utc_now


EventHandler = Callable[["Event"], None]


@dataclass(slots=True)
class Event:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
    source: str = "system"
    event_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str):
            raise TypeError("Event name must be text.")

        self.name = self.name.strip()

        if not self.name:
            raise ValueError("Event name cannot be empty.")

        if not isinstance(self.payload, dict):
            raise TypeError("Event payload must be a dictionary.")

        if not isinstance(self.source, str):
            raise TypeError("Event source must be text.")

        self.source = self.source.strip() or "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "name": self.name,
            "payload": dict(self.payload),
            "source": self.source,
            "created_at": self.created_at,
        }


class EventBus:
    """
    Thread-safe event publisher and subscriber registry.

    A subscriber failure is logged but does not stop delivery to
    the remaining subscribers.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
    ) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()
        self._logger = logger or logging.getLogger("mama_ai.event_bus")

    def subscribe(
        self,
        event_name: str,
        handler: EventHandler,
    ) -> None:
        event_name = self._validate_event_name(event_name)

        if not callable(handler):
            raise TypeError("Event handler must be callable.")

        with self._lock:
            handlers = self._subscribers[event_name]

            if handler not in handlers:
                handlers.append(handler)

    def unsubscribe(
        self,
        event_name: str,
        handler: EventHandler,
    ) -> bool:
        event_name = self._validate_event_name(event_name)

        with self._lock:
            handlers = self._subscribers.get(event_name)

            if not handlers or handler not in handlers:
                return False

            handlers.remove(handler)

            if not handlers:
                self._subscribers.pop(event_name, None)

            return True

    def publish(
        self,
        event: Event | str,
        payload: dict[str, Any] | None = None,
        *,
        source: str = "system",
    ) -> Event:
        if isinstance(event, str):
            event = Event(
                name=event,
                payload=dict(payload or {}),
                source=source,
            )
        elif payload is not None:
            raise ValueError(
                "Payload cannot be supplied when publishing an Event object."
            )

        if not isinstance(event, Event):
            raise TypeError("Published value must be an Event or event name.")

        with self._lock:
            handlers = list(self._subscribers.get(event.name, []))
            wildcard_handlers = list(self._subscribers.get("*", []))

        for handler in handlers + wildcard_handlers:
            try:
                handler(event)
            except Exception:
                self._logger.exception(
                    "Event handler failed | event=%s | handler=%r",
                    event.name,
                    handler,
                )

        return event

    def subscriber_count(self, event_name: str) -> int:
        event_name = self._validate_event_name(event_name)

        with self._lock:
            return len(self._subscribers.get(event_name, []))

    def clear(self, event_name: str | None = None) -> None:
        with self._lock:
            if event_name is None:
                self._subscribers.clear()
                return

            event_name = self._validate_event_name(event_name)
            self._subscribers.pop(event_name, None)

    @staticmethod
    def _validate_event_name(event_name: str) -> str:
        if not isinstance(event_name, str):
            raise TypeError("Event name must be text.")

        event_name = event_name.strip()

        if not event_name:
            raise ValueError("Event name cannot be empty.")

        return event_name


event_bus = EventBus()


__all__ = [
    "Event",
    "EventBus",
    "EventHandler",
    "event_bus",
]