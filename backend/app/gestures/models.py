"""Core data contracts for Mama AI hand-gesture processing.

The gesture core is dependency-free so recognition, safety, and dispatch logic
can be tested without a webcam, MediaPipe, OpenCV, or a desktop session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Mapping, Sequence


class HandLandmark(IntEnum):
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20


class Gesture(str, Enum):
    NONE = "none"
    POINT = "point"
    PINCH_INDEX = "pinch_index"
    PINCH_MIDDLE = "pinch_middle"
    PINCH_RING = "pinch_ring"
    TWO_FINGER = "two_finger"
    FIST = "fist"
    OPEN_PALM = "open_palm"
    THREE_FINGER = "three_finger"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    SWIPE_UP = "swipe_up"
    SWIPE_DOWN = "swipe_down"


class EngineEventType(str, Enum):
    OBSERVATION = "observation"
    ACTION = "action"
    ARMED = "armed"
    DISARMED = "disarmed"
    PROFILE_CHANGED = "profile_changed"
    WATCHDOG = "watchdog"
    ERROR = "error"


@dataclass(frozen=True)
class Point3D:
    x: float
    y: float
    z: float = 0.0

    def __post_init__(self) -> None:
        for name, value in (("x", self.x), ("y", self.y), ("z", self.z)):
            if not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric.")


@dataclass(frozen=True)
class HandFrame:
    landmarks: tuple[Point3D, ...]
    timestamp: float
    confidence: float = 1.0
    handedness: str = "unknown"
    source_width: int = 1
    source_height: int = 1

    def __post_init__(self) -> None:
        if len(self.landmarks) != 21:
            raise ValueError("A hand frame must contain exactly 21 landmarks.")
        if self.timestamp < 0:
            raise ValueError("timestamp must not be negative.")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1.")
        if self.source_width < 1 or self.source_height < 1:
            raise ValueError("source dimensions must be positive.")

    def point(self, landmark: HandLandmark) -> Point3D:
        return self.landmarks[int(landmark)]


@dataclass(frozen=True)
class GestureObservation:
    gesture: Gesture
    timestamp: float
    confidence: float
    cursor_point: Point3D
    palm_center: Point3D
    palm_scale: float
    extended_fingers: tuple[bool, bool, bool, bool]
    metrics: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ActionSpec:
    action: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    dwell_ms: int = 120
    cooldown_ms: int = 350

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise ValueError("action must not be empty.")
        if self.dwell_ms < 0:
            raise ValueError("dwell_ms must not be negative.")
        if self.cooldown_ms < 0:
            raise ValueError("cooldown_ms must not be negative.")


@dataclass(frozen=True)
class GestureProfile:
    name: str
    description: str
    actions: Mapping[Gesture, ActionSpec]
    window_title_patterns: tuple[str, ...] = ()
    auto_select: bool = False
    priority: int = 0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("profile name must not be empty.")


@dataclass(frozen=True)
class ActionCommand:
    action: str
    parameters: Mapping[str, Any]
    gesture: Gesture
    profile: str
    timestamp: float


@dataclass(frozen=True)
class EngineEvent:
    type: EngineEventType
    timestamp: float
    message: str
    gesture: Gesture = Gesture.NONE
    profile: str = ""
    command: ActionCommand | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


def points_from_sequence(values: Sequence[Sequence[float]]) -> tuple[Point3D, ...]:
    """Convert a serializable landmark sequence into validated points."""

    points: list[Point3D] = []
    for value in values:
        if len(value) not in {2, 3}:
            raise ValueError("Each landmark must contain two or three values.")
        points.append(
            Point3D(
                x=float(value[0]),
                y=float(value[1]),
                z=float(value[2]) if len(value) == 3 else 0.0,
            )
        )
    return tuple(points)
