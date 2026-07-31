"""Geometry helpers for normalized hand landmarks."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.gestures.models import HandFrame, HandLandmark, Point3D


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def distance_2d(first: Point3D, second: Point3D) -> float:
    return math.hypot(first.x - second.x, first.y - second.y)


def angle_degrees(first: Point3D, vertex: Point3D, third: Point3D) -> float:
    first_vector = (first.x - vertex.x, first.y - vertex.y)
    second_vector = (third.x - vertex.x, third.y - vertex.y)
    first_length = math.hypot(*first_vector)
    second_length = math.hypot(*second_vector)
    if first_length <= 1e-9 or second_length <= 1e-9:
        return 0.0
    cosine = (
        first_vector[0] * second_vector[0]
        + first_vector[1] * second_vector[1]
    ) / (first_length * second_length)
    return math.degrees(math.acos(clamp(cosine, -1.0, 1.0)))


def average_point(*points: Point3D) -> Point3D:
    if not points:
        raise ValueError("At least one point is required.")
    count = float(len(points))
    return Point3D(
        x=sum(point.x for point in points) / count,
        y=sum(point.y for point in points) / count,
        z=sum(point.z for point in points) / count,
    )


def palm_center(frame: HandFrame) -> Point3D:
    return average_point(
        frame.point(HandLandmark.WRIST),
        frame.point(HandLandmark.INDEX_MCP),
        frame.point(HandLandmark.MIDDLE_MCP),
        frame.point(HandLandmark.RING_MCP),
        frame.point(HandLandmark.PINKY_MCP),
    )


def palm_scale(frame: HandFrame) -> float:
    scale = distance_2d(
        frame.point(HandLandmark.WRIST),
        frame.point(HandLandmark.MIDDLE_MCP),
    )
    return max(scale, 1e-6)


def normalized_distance(
    frame: HandFrame,
    first: HandLandmark,
    second: HandLandmark,
) -> float:
    return distance_2d(frame.point(first), frame.point(second)) / palm_scale(frame)


_FINGER_JOINTS = (
    (HandLandmark.INDEX_MCP, HandLandmark.INDEX_PIP, HandLandmark.INDEX_TIP),
    (HandLandmark.MIDDLE_MCP, HandLandmark.MIDDLE_PIP, HandLandmark.MIDDLE_TIP),
    (HandLandmark.RING_MCP, HandLandmark.RING_PIP, HandLandmark.RING_TIP),
    (HandLandmark.PINKY_MCP, HandLandmark.PINKY_PIP, HandLandmark.PINKY_TIP),
)


def extended_fingers(
    frame: HandFrame,
    *,
    minimum_angle_degrees: float = 145.0,
    minimum_reach_ratio: float = 1.12,
) -> tuple[bool, bool, bool, bool]:
    wrist = frame.point(HandLandmark.WRIST)
    states: list[bool] = []
    for mcp_index, pip_index, tip_index in _FINGER_JOINTS:
        mcp = frame.point(mcp_index)
        pip = frame.point(pip_index)
        tip = frame.point(tip_index)
        joint_angle = angle_degrees(mcp, pip, tip)
        pip_reach = distance_2d(wrist, pip)
        tip_reach = distance_2d(wrist, tip)
        states.append(
            joint_angle >= minimum_angle_degrees
            and tip_reach >= pip_reach * minimum_reach_ratio
        )
    return tuple(states)  # type: ignore[return-value]


@dataclass
class ExponentialPointSmoother:
    alpha: float = 0.35
    _value: Point3D | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha <= 1.0:
            raise ValueError("alpha must be greater than 0 and at most 1.")

    def reset(self) -> None:
        self._value = None

    def update(self, point: Point3D) -> Point3D:
        if self._value is None:
            self._value = point
            return point
        retained = 1.0 - self.alpha
        self._value = Point3D(
            x=self._value.x * retained + point.x * self.alpha,
            y=self._value.y * retained + point.y * self.alpha,
            z=self._value.z * retained + point.z * self.alpha,
        )
        return self._value


@dataclass
class CursorMapper:
    margin: float = 0.12
    mirror_x: bool = True
    maximum_step_pixels: float = 180.0
    _last: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.margin < 0.45:
            raise ValueError("margin must be between 0 and 0.45.")
        if self.maximum_step_pixels <= 0:
            raise ValueError("maximum_step_pixels must be positive.")

    def reset(self) -> None:
        self._last = None

    def map(
        self,
        point: Point3D,
        screen_width: int,
        screen_height: int,
    ) -> tuple[int, int]:
        if screen_width < 1 or screen_height < 1:
            raise ValueError("screen dimensions must be positive.")
        span = 1.0 - self.margin * 2.0
        normalized_x = clamp((point.x - self.margin) / span, 0.0, 1.0)
        normalized_y = clamp((point.y - self.margin) / span, 0.0, 1.0)
        if self.mirror_x:
            normalized_x = 1.0 - normalized_x
        target = (
            int(round(normalized_x * (screen_width - 1))),
            int(round(normalized_y * (screen_height - 1))),
        )
        if self._last is None:
            self._last = target
            return target
        delta_x = target[0] - self._last[0]
        delta_y = target[1] - self._last[1]
        step = math.hypot(delta_x, delta_y)
        if step > self.maximum_step_pixels:
            ratio = self.maximum_step_pixels / step
            target = (
                int(round(self._last[0] + delta_x * ratio)),
                int(round(self._last[1] + delta_y * ratio)),
            )
        self._last = target
        return target
