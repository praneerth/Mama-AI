"""Fail-closed safety state for desktop gesture control."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GestureSafetyController:
    stale_frame_timeout_ms: int = 750
    arm_toggle_cooldown_ms: int = 1800
    armed: bool = False
    emergency_latched: bool = False
    last_frame_at: float | None = None
    last_toggle_at: float | None = None

    def __post_init__(self) -> None:
        if self.stale_frame_timeout_ms < 1:
            raise ValueError("stale_frame_timeout_ms must be positive.")
        if self.arm_toggle_cooldown_ms < 1:
            raise ValueError("arm_toggle_cooldown_ms must be positive.")

    def observe_frame(self, timestamp: float) -> None:
        self.last_frame_at = timestamp

    def toggle(self, timestamp: float) -> bool:
        if self.emergency_latched:
            return False
        if self.last_toggle_at is not None:
            elapsed = (timestamp - self.last_toggle_at) * 1000.0
            if elapsed < self.arm_toggle_cooldown_ms:
                return False
        self.armed = not self.armed
        self.last_toggle_at = timestamp
        return True

    def disarm(self) -> bool:
        changed = self.armed
        self.armed = False
        return changed

    def emergency_stop(self) -> bool:
        changed = self.armed or not self.emergency_latched
        self.armed = False
        self.emergency_latched = True
        return changed

    def reset_emergency(self) -> None:
        self.emergency_latched = False
        self.armed = False

    def watchdog_expired(self, timestamp: float) -> bool:
        if self.last_frame_at is None:
            return False
        elapsed_ms = (timestamp - self.last_frame_at) * 1000.0
        if elapsed_ms <= self.stale_frame_timeout_ms:
            return False
        self.last_frame_at = None
        return self.disarm()

    @property
    def actions_allowed(self) -> bool:
        return self.armed and not self.emergency_latched
