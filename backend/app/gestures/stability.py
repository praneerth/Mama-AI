"""Temporal filters for stable poses, cooldowns, scrolling, and swipes."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.gestures.models import Gesture, Point3D


@dataclass
class GestureStabilizer:
    """Require a small run of matching frames before changing poses.

    This removes one-frame MediaPipe classification flicker while keeping the
    pointer and scroll gestures responsive enough for desktop use.
    """

    enter_frames: int = 3
    release_frames: int = 2
    stable: Gesture = Gesture.NONE
    _candidate: Gesture = Gesture.NONE
    _candidate_count: int = 0

    def __post_init__(self) -> None:
        if self.enter_frames < 1 or self.release_frames < 1:
            raise ValueError("Gesture stabilizer frame counts must be positive.")

    def reset(self) -> None:
        self.stable = Gesture.NONE
        self._candidate = Gesture.NONE
        self._candidate_count = 0

    def update(self, gesture: Gesture) -> Gesture:
        if gesture == self.stable:
            self._candidate = Gesture.NONE
            self._candidate_count = 0
            return self.stable

        if gesture == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = gesture
            self._candidate_count = 1

        threshold = (
            self.release_frames if gesture == Gesture.NONE else self.enter_frames
        )
        if self._candidate_count >= threshold:
            self.stable = gesture
            self._candidate = Gesture.NONE
            self._candidate_count = 0
        return self.stable


@dataclass
class GestureLatch:
    current: Gesture = Gesture.NONE
    first_seen_at: float = 0.0
    fired: bool = False

    def reset(self) -> None:
        self.current = Gesture.NONE
        self.first_seen_at = 0.0
        self.fired = False

    def update(
        self,
        gesture: Gesture,
        timestamp: float,
        dwell_ms: int,
    ) -> bool:
        if gesture != self.current:
            self.current = gesture
            self.first_seen_at = timestamp
            self.fired = False
            return dwell_ms == 0 and gesture != Gesture.NONE
        if gesture == Gesture.NONE or self.fired:
            return False
        if (timestamp - self.first_seen_at) * 1000.0 >= dwell_ms:
            self.fired = True
            return True
        return False


@dataclass
class CooldownRegistry:
    _last_fired: dict[str, float] = field(default_factory=dict)

    def ready(self, key: str, timestamp: float, cooldown_ms: int) -> bool:
        previous = self._last_fired.get(key)
        if previous is None:
            return True
        return (timestamp - previous) * 1000.0 >= cooldown_ms

    def mark(self, key: str, timestamp: float) -> None:
        self._last_fired[key] = timestamp

    def clear(self) -> None:
        self._last_fired.clear()


@dataclass
class ScrollTracker:
    dead_zone: float = 0.010
    scale: float = 240.0
    smoothing_alpha: float = 0.35
    maximum_step: int = 18
    _previous_y: float | None = None
    _filtered_delta: float = 0.0
    _accumulator: float = 0.0

    def __post_init__(self) -> None:
        if self.dead_zone < 0:
            raise ValueError("dead_zone must not be negative.")
        if self.scale <= 0:
            raise ValueError("scale must be positive.")
        if not 0.0 < self.smoothing_alpha <= 1.0:
            raise ValueError("smoothing_alpha must be greater than 0 and at most 1.")
        if self.maximum_step < 1:
            raise ValueError("maximum_step must be positive.")

    def reset(self) -> None:
        self._previous_y = None
        self._filtered_delta = 0.0
        self._accumulator = 0.0

    def update(self, y: float) -> int:
        if self._previous_y is None:
            self._previous_y = y
            return 0

        raw_delta = self._previous_y - y
        self._previous_y = y
        if abs(raw_delta) < self.dead_zone:
            self._filtered_delta *= 0.5
            return 0

        alpha = self.smoothing_alpha
        self._filtered_delta = (
            alpha * raw_delta + (1.0 - alpha) * self._filtered_delta
        )
        self._accumulator += self._filtered_delta * self.scale

        amount = int(self._accumulator)
        if amount == 0:
            return 0
        amount = max(-self.maximum_step, min(self.maximum_step, amount))
        self._accumulator -= amount
        return amount


@dataclass
class SwipeDetector:
    window_ms: int = 450
    minimum_distance: float = 0.20
    maximum_cross_axis: float = 0.14
    _history: deque[tuple[float, Point3D]] = field(default_factory=deque)
    _latched: bool = False

    def reset(self) -> None:
        self._history.clear()
        self._latched = False

    def update(
        self,
        point: Point3D,
        timestamp: float,
        enabled: bool,
    ) -> Gesture:
        if not enabled:
            self.reset()
            return Gesture.NONE
        cutoff = timestamp - self.window_ms / 1000.0
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()
        self._history.append((timestamp, point))
        if self._latched or len(self._history) < 2:
            return Gesture.NONE
        start = self._history[0][1]
        delta_x = point.x - start.x
        delta_y = point.y - start.y
        horizontal = abs(delta_x) >= self.minimum_distance
        vertical = abs(delta_y) >= self.minimum_distance
        if horizontal and abs(delta_y) <= self.maximum_cross_axis:
            self._latched = True
            return Gesture.SWIPE_RIGHT if delta_x > 0 else Gesture.SWIPE_LEFT
        if vertical and abs(delta_x) <= self.maximum_cross_axis:
            self._latched = True
            return Gesture.SWIPE_DOWN if delta_y > 0 else Gesture.SWIPE_UP
        return Gesture.NONE
