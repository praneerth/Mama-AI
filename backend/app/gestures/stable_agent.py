"""Low-latency Windows hand-gesture control for Mama AI.

This module is intentionally independent from the FastAPI/backend settings so
it can run inside a small dedicated gesture virtual environment. Camera frames
are captured on a background thread and only the newest frame is processed,
which prevents the delayed-frame backlog that makes gesture control feel laggy.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.gestures.geometry import (
    average_point,
    distance_2d,
    extended_fingers,
    palm_center,
    palm_scale,
)
from app.gestures.models import (
    Gesture,
    GestureObservation,
    HandFrame,
    HandLandmark,
    Point3D,
)
from app.gestures.window_context import WindowsEmergencyHotkey


LOGGER = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class StableGestureConfig:
    """Configuration tuned for low latency and predictable actions."""

    camera_index: int = 0
    camera_width: int = 320
    camera_height: int = 240
    camera_fps: int = 30
    minimum_detection_confidence: float = 0.65
    minimum_tracking_confidence: float = 0.65
    minimum_frame_confidence: float = 0.45
    model_complexity: int = 0
    preview_enabled: bool = True
    dry_run: bool = False
    pose_enter_frames: int = 2
    pose_release_frames: int = 5
    arm_hold_seconds: float = 0.55
    disarm_hold_seconds: float = 1.20
    action_warmup_seconds: float = 0.18
    no_hand_disarm_seconds: float = 8.0
    pinch_enter_ratio: float = 0.44
    pinch_release_ratio: float = 0.62
    middle_pinch_enter_ratio: float = 0.48
    middle_pinch_release_ratio: float = 0.68
    ring_pinch_enter_ratio: float = 0.52
    ring_pinch_release_ratio: float = 0.72
    pinch_enter_frames: int = 2
    pinch_release_frames: int = 2
    click_cooldown_seconds: float = 0.45
    drag_hold_seconds: float = 0.55
    pointer_sensitivity_x: float = 2.25
    pointer_sensitivity_y: float = 2.00
    pointer_min_alpha: float = 0.18
    pointer_max_alpha: float = 0.72
    pointer_speed_reference_pixels: float = 260.0
    pointer_max_step_pixels: float = 150.0
    pointer_dead_zone_pixels: float = 1.5
    scroll_dead_zone: float = 0.003
    scroll_scale: float = 34.0
    scroll_maximum_notches: int = 2
    swipe_min_horizontal_ratio: float = 0.11
    swipe_max_vertical_ratio: float = 0.40
    swipe_max_duration_seconds: float = 1.80
    swipe_cooldown_seconds: float = 0.70
    simple_mode: bool = False
    simple_auto_arm_seconds: float = 0.20
    simple_no_hand_disarm_seconds: float = 2.00

    def __post_init__(self) -> None:
        if self.camera_index < 0:
            raise ValueError("camera_index must not be negative.")
        if self.camera_width < 160 or self.camera_height < 120:
            raise ValueError("camera dimensions are too small.")
        if self.camera_fps < 1:
            raise ValueError("camera_fps must be positive.")
        if self.model_complexity not in {0, 1}:
            raise ValueError("model_complexity must be 0 or 1.")
        for name, value in (
            ("minimum_detection_confidence", self.minimum_detection_confidence),
            ("minimum_tracking_confidence", self.minimum_tracking_confidence),
            ("minimum_frame_confidence", self.minimum_frame_confidence),
            ("pointer_min_alpha", self.pointer_min_alpha),
            ("pointer_max_alpha", self.pointer_max_alpha),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be greater than 0 and at most 1.")
        if self.pointer_min_alpha > self.pointer_max_alpha:
            raise ValueError("pointer_min_alpha must not exceed pointer_max_alpha.")
        if not 0.05 <= self.swipe_min_horizontal_ratio <= 0.60:
            raise ValueError("swipe_min_horizontal_ratio must be between 0.05 and 0.60.")
        if not 0.03 <= self.swipe_max_vertical_ratio <= 0.50:
            raise ValueError("swipe_max_vertical_ratio must be between 0.03 and 0.50.")
        if self.swipe_max_duration_seconds <= 0:
            raise ValueError("swipe_max_duration_seconds must be positive.")
        if self.swipe_cooldown_seconds < 0:
            raise ValueError("swipe_cooldown_seconds must not be negative.")
        if self.simple_auto_arm_seconds < 0:
            raise ValueError("simple_auto_arm_seconds must not be negative.")
        if self.simple_no_hand_disarm_seconds <= 0:
            raise ValueError("simple_no_hand_disarm_seconds must be positive.")
        for name, enter, release in (
            ("index pinch", self.pinch_enter_ratio, self.pinch_release_ratio),
            ("middle pinch", self.middle_pinch_enter_ratio, self.middle_pinch_release_ratio),
            ("ring pinch", self.ring_pinch_enter_ratio, self.ring_pinch_release_ratio),
        ):
            if not 0 < enter < release:
                raise ValueError(f"{name} thresholds are invalid.")


class RobustGestureRecognizer:
    """Tolerant pose recognition for real webcam landmarks.

    Pinching is reported as a metric instead of replacing the hand pose. This
    keeps pointer movement stable while the thumb approaches the index finger.
    """

    def recognize(self, frame: HandFrame) -> GestureObservation:
        center = palm_center(frame)
        palm_length = palm_scale(frame)
        palm_width = distance_2d(
            frame.point(HandLandmark.INDEX_MCP),
            frame.point(HandLandmark.PINKY_MCP),
        )
        scale = max(palm_length, palm_width, 1e-6)
        fingers = extended_fingers(
            frame,
            minimum_angle_degrees=122.0,
            minimum_reach_ratio=1.035,
        )
        index, middle, ring, pinky = fingers
        extended_count = sum(1 for state in fingers if state)

        if extended_count >= 3:
            gesture = Gesture.OPEN_PALM
        elif index and middle and not ring and not pinky:
            gesture = Gesture.TWO_FINGER
        elif index and not middle and not ring and not pinky:
            gesture = Gesture.POINT
        elif extended_count == 0:
            gesture = Gesture.FIST
        else:
            gesture = Gesture.NONE

        thumb_tip = frame.point(HandLandmark.THUMB_TIP)
        index_pinch = distance_2d(
            thumb_tip,
            frame.point(HandLandmark.INDEX_TIP),
        ) / scale
        middle_pinch = distance_2d(
            thumb_tip,
            frame.point(HandLandmark.MIDDLE_TIP),
        ) / scale
        ring_pinch = distance_2d(
            thumb_tip,
            frame.point(HandLandmark.RING_TIP),
        ) / scale
        scroll_point = average_point(
            frame.point(HandLandmark.INDEX_TIP),
            frame.point(HandLandmark.MIDDLE_TIP),
        )
        confidence = min(
            frame.confidence,
            max(0.0, min(1.0, scale / 0.10)),
        )
        return GestureObservation(
            gesture=gesture,
            timestamp=frame.timestamp,
            confidence=confidence,
            cursor_point=frame.point(HandLandmark.INDEX_TIP),
            palm_center=center,
            palm_scale=scale,
            extended_fingers=fingers,
            metrics={
                "index_pinch": index_pinch,
                "middle_pinch": middle_pinch,
                "ring_pinch": ring_pinch,
                "scroll_y": scroll_point.y,
                "extended_count": float(extended_count),
            },
        )


@dataclass
class PoseDebouncer:
    """Debounce MediaPipe pose flicker without delaying continuous movement."""

    enter_frames: int = 2
    release_frames: int = 4
    stable: Gesture = Gesture.NONE
    _candidate: Gesture = Gesture.NONE
    _count: int = 0

    def reset(self) -> None:
        self.stable = Gesture.NONE
        self._candidate = Gesture.NONE
        self._count = 0

    def update(self, raw: Gesture) -> Gesture:
        if raw == self.stable:
            self._candidate = Gesture.NONE
            self._count = 0
            return self.stable
        if raw == self._candidate:
            self._count += 1
        else:
            self._candidate = raw
            self._count = 1
        threshold = self.release_frames if raw == Gesture.NONE else self.enter_frames
        if self._count >= threshold:
            self.stable = raw
            self._candidate = Gesture.NONE
            self._count = 0
        return self.stable


@dataclass
class HoldDetector:
    required_seconds: float
    _gesture: Gesture = Gesture.NONE
    _started_at: float | None = None
    _fired: bool = False

    def reset(self) -> None:
        self._gesture = Gesture.NONE
        self._started_at = None
        self._fired = False

    def update(self, gesture: Gesture, expected: Gesture, timestamp: float) -> bool:
        if gesture != expected:
            self.reset()
            return False
        if self._gesture != expected or self._started_at is None:
            self._gesture = expected
            self._started_at = timestamp
            self._fired = False
            return False
        if self._fired:
            return False
        if timestamp - self._started_at >= self.required_seconds:
            self._fired = True
            return True
        return False


@dataclass
class PinchLatch:
    enter_ratio: float = 0.44
    release_ratio: float = 0.62
    cooldown_seconds: float = 0.45
    active: bool = False
    last_click_at: float | None = None
    enter_frames: int = 1
    release_frames: int = 1
    _enter_count: int = 0
    _release_count: int = 0

    def reset(self) -> None:
        self.active = False
        self._enter_count = 0
        self._release_count = 0

    def update(self, ratio: float, timestamp: float) -> bool:
        if self.active:
            if ratio >= self.release_ratio:
                self._release_count += 1
                if self._release_count >= self.release_frames:
                    self.active = False
                    self._release_count = 0
            else:
                self._release_count = 0
            return False

        if ratio > self.enter_ratio:
            self._enter_count = 0
            return False
        self._enter_count += 1
        if self._enter_count < self.enter_frames:
            return False
        self._enter_count = 0
        if (
            self.last_click_at is not None
            and timestamp - self.last_click_at < self.cooldown_seconds
        ):
            self.active = True
            return False
        self.active = True
        self.last_click_at = timestamp
        return True


@dataclass
class RelativePointerController:
    """Touchpad-style relative mapping that cannot teleport to screen edges."""

    sensitivity_x: float = 2.25
    sensitivity_y: float = 2.00
    minimum_alpha: float = 0.18
    maximum_alpha: float = 0.72
    speed_reference_pixels: float = 260.0
    maximum_step_pixels: float = 150.0
    dead_zone_pixels: float = 1.5
    _hand_anchor: Point3D | None = None
    _cursor_anchor: tuple[int, int] | None = None
    _filtered: tuple[float, float] | None = None

    def reset(self) -> None:
        self._hand_anchor = None
        self._cursor_anchor = None
        self._filtered = None

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def update(
        self,
        point: Point3D,
        cursor: tuple[int, int],
        screen: tuple[int, int],
    ) -> tuple[int, int]:
        width, height = screen
        if self._hand_anchor is None or self._cursor_anchor is None:
            self._hand_anchor = point
            self._cursor_anchor = cursor
            self._filtered = (float(cursor[0]), float(cursor[1]))
            return cursor

        target_x = self._cursor_anchor[0] + (
            point.x - self._hand_anchor.x
        ) * width * self.sensitivity_x
        target_y = self._cursor_anchor[1] + (
            point.y - self._hand_anchor.y
        ) * height * self.sensitivity_y
        target_x = self._clamp(target_x, 3.0, float(max(3, width - 4)))
        target_y = self._clamp(target_y, 3.0, float(max(3, height - 4)))

        current_x, current_y = self._filtered or (float(cursor[0]), float(cursor[1]))
        delta_x = target_x - current_x
        delta_y = target_y - current_y
        distance = (delta_x * delta_x + delta_y * delta_y) ** 0.5
        if distance <= self.dead_zone_pixels:
            return int(round(current_x)), int(round(current_y))

        speed_ratio = min(1.0, distance / self.speed_reference_pixels)
        alpha = self.minimum_alpha + (
            self.maximum_alpha - self.minimum_alpha
        ) * speed_ratio
        step_x = delta_x * alpha
        step_y = delta_y * alpha
        step_distance = (step_x * step_x + step_y * step_y) ** 0.5
        if step_distance > self.maximum_step_pixels:
            factor = self.maximum_step_pixels / step_distance
            step_x *= factor
            step_y *= factor

        current_x += step_x
        current_y += step_y
        self._filtered = (current_x, current_y)
        return int(round(current_x)), int(round(current_y))


@dataclass
class ScrollController:
    dead_zone: float = 0.004
    scale: float = 26.0
    maximum_notches: int = 2
    _previous_y: float | None = None
    _accumulator: float = 0.0

    def reset(self) -> None:
        self._previous_y = None
        self._accumulator = 0.0

    def update(self, y: float) -> int:
        if self._previous_y is None:
            self._previous_y = y
            return 0
        delta = self._previous_y - y
        self._previous_y = y
        if abs(delta) < self.dead_zone:
            return 0
        self._accumulator += delta * self.scale
        amount = int(self._accumulator)
        if amount == 0:
            return 0
        amount = max(-self.maximum_notches, min(self.maximum_notches, amount))
        self._accumulator -= amount
        return amount


@dataclass
class OpenPalmSwipeDetector:
    """Recognize one deliberate horizontal open-palm swipe per pose."""

    minimum_horizontal_distance: float = 0.18
    maximum_vertical_distance: float = 0.20
    maximum_duration_seconds: float = 1.10
    cooldown_seconds: float = 0.90
    _start_point: Point3D | None = None
    _started_at: float | None = None
    _last_fired_at: float | None = None
    _fired_for_pose: bool = False

    def reset_pose(self) -> None:
        self._start_point = None
        self._started_at = None
        self._fired_for_pose = False

    def reset_all(self) -> None:
        self.reset_pose()
        self._last_fired_at = None

    def update(self, point: Point3D, timestamp: float) -> str | None:
        if self._fired_for_pose:
            if (
                self._last_fired_at is None
                or timestamp - self._last_fired_at < self.cooldown_seconds
            ):
                return None
            # Re-arm automatically while the palm remains open. The user only
            # needs to pause briefly before making the next swipe.
            self._fired_for_pose = False
            self._start_point = point
            self._started_at = timestamp
            return None
        if (
            self._last_fired_at is not None
            and timestamp - self._last_fired_at < self.cooldown_seconds
        ):
            return None
        if self._start_point is None or self._started_at is None:
            self._start_point = point
            self._started_at = timestamp
            return None

        elapsed = timestamp - self._started_at
        if elapsed > self.maximum_duration_seconds:
            self._start_point = point
            self._started_at = timestamp
            return None

        delta_x = point.x - self._start_point.x
        delta_y = point.y - self._start_point.y
        if abs(delta_y) > self.maximum_vertical_distance:
            self._start_point = point
            self._started_at = timestamp
            return None
        if abs(delta_x) < self.minimum_horizontal_distance:
            return None

        direction = "right" if delta_x > 0 else "left"
        self._last_fired_at = timestamp
        self._fired_for_pose = True
        return direction


class RecordingMouse:
    """Dry-run mouse implementation used by tests and safe calibration."""

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self.width = width
        self.height = height
        self.position = (width // 2, height // 2)
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def screen_size(self) -> tuple[int, int]:
        return self.width, self.height

    def cursor_position(self) -> tuple[int, int]:
        return self.position

    def move(self, x: int, y: int) -> None:
        self.position = (x, y)
        self.calls.append(("move", (x, y)))

    def left_click(self) -> None:
        self.calls.append(("left_click", ()))

    def left_down(self) -> None:
        self.calls.append(("left_down", ()))

    def left_up(self) -> None:
        self.calls.append(("left_up", ()))

    def right_click(self) -> None:
        self.calls.append(("right_click", ()))

    def double_click(self) -> None:
        self.calls.append(("double_click", ()))

    def scroll(self, notches: int) -> None:
        self.calls.append(("scroll", (notches,)))


class NativeWindowsMouse:
    """Low-overhead Windows mouse control using User32 instead of PyAutoGUI."""

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800
    WHEEL_DELTA = 120

    class _Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def __init__(self, user32: Any | None = None) -> None:
        if os.name != "nt" and user32 is None:
            raise RuntimeError("Live stable gestures currently require Windows.")
        self.user32 = user32 or ctypes.windll.user32

    def screen_size(self) -> tuple[int, int]:
        return int(self.user32.GetSystemMetrics(0)), int(
            self.user32.GetSystemMetrics(1)
        )

    def cursor_position(self) -> tuple[int, int]:
        point = self._Point()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            raise RuntimeError("Windows could not read the cursor position.")
        return int(point.x), int(point.y)

    def move(self, x: int, y: int) -> None:
        self.user32.SetCursorPos(int(x), int(y))

    def left_click(self) -> None:
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def left_down(self) -> None:
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def left_up(self) -> None:
        self.user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def right_click(self) -> None:
        self.user32.mouse_event(self.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
        self.user32.mouse_event(self.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

    def double_click(self) -> None:
        self.left_click()
        time.sleep(0.06)
        self.left_click()

    def scroll(self, notches: int) -> None:
        self.user32.mouse_event(
            self.MOUSEEVENTF_WHEEL,
            0,
            0,
            int(notches * self.WHEEL_DELTA),
            0,
        )


class RecordingKeyboard:
    """Dry-run keyboard implementation used by swipe unit tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def browser_back(self) -> None:
        self.calls.append(("browser_back", ()))

    def browser_forward(self) -> None:
        self.calls.append(("browser_forward", ()))


class NativeWindowsKeyboard:
    """Send browser navigation shortcuts through the Windows User32 API."""

    VK_MENU = 0x12
    VK_LEFT = 0x25
    VK_RIGHT = 0x27
    KEYEVENTF_KEYUP = 0x0002

    def __init__(self, user32: Any | None = None) -> None:
        if os.name != "nt" and user32 is None:
            raise RuntimeError("Live swipe gestures currently require Windows.")
        self.user32 = user32 or ctypes.windll.user32

    def _alt_arrow(self, arrow_key: int) -> None:
        self.user32.keybd_event(self.VK_MENU, 0, 0, 0)
        self.user32.keybd_event(arrow_key, 0, 0, 0)
        self.user32.keybd_event(arrow_key, 0, self.KEYEVENTF_KEYUP, 0)
        self.user32.keybd_event(self.VK_MENU, 0, self.KEYEVENTF_KEYUP, 0)

    def browser_back(self) -> None:
        self._alt_arrow(self.VK_LEFT)

    def browser_forward(self) -> None:
        self._alt_arrow(self.VK_RIGHT)


class LatestFrameCapture:
    """Continuously capture frames and expose only the newest frame."""

    def __init__(self, cv2: Any, config: StableGestureConfig) -> None:
        self.cv2 = cv2
        self.config = config
        self.capture = self._open_capture()
        if not self.capture.isOpened():
            self.capture.release()
            raise RuntimeError(f"Unable to open camera index {config.camera_index}.")
        self._configure()
        self._lock = threading.Lock()
        self._latest: Any = None
        self._sequence = 0
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._reader,
            name="mama-ai-gesture-camera",
            daemon=True,
        )

    def _open_capture(self) -> Any:
        if os.name == "nt" and hasattr(self.cv2, "CAP_DSHOW"):
            capture = self.cv2.VideoCapture(
                self.config.camera_index,
                self.cv2.CAP_DSHOW,
            )
            if capture.isOpened():
                return capture
            capture.release()
        return self.cv2.VideoCapture(self.config.camera_index)

    def _configure(self) -> None:
        if hasattr(self.cv2, "VideoWriter_fourcc"):
            fourcc = self.cv2.VideoWriter_fourcc(*"MJPG")
            self.capture.set(self.cv2.CAP_PROP_FOURCC, fourcc)
        for property_name, value in (
            ("CAP_PROP_FRAME_WIDTH", self.config.camera_width),
            ("CAP_PROP_FRAME_HEIGHT", self.config.camera_height),
            ("CAP_PROP_FPS", self.config.camera_fps),
            ("CAP_PROP_BUFFERSIZE", 1),
        ):
            property_id = getattr(self.cv2, property_name, None)
            if property_id is not None:
                self.capture.set(property_id, float(value))

    def start(self) -> "LatestFrameCapture":
        self._thread.start()
        return self

    def _reader(self) -> None:
        while not self._stopped.is_set():
            ok, frame = self.capture.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            with self._lock:
                self._latest = frame
                self._sequence += 1

    def latest(self, previous_sequence: int) -> tuple[int, Any | None]:
        with self._lock:
            if self._sequence == previous_sequence or self._latest is None:
                return previous_sequence, None
            return self._sequence, self._latest

    def wait_until_ready(self, timeout_seconds: float = 3.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self._lock:
                if self._latest is not None:
                    return
            time.sleep(0.02)
        raise RuntimeError("Camera opened but did not provide frames.")

    def close(self) -> None:
        self._stopped.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self.capture.release()


@dataclass(frozen=True)
class StableGestureSummary:
    frames: int
    valid_hand_frames: int
    actions: int
    exit_reason: str


class StableGestureAgent:
    def __init__(
        self,
        config: StableGestureConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
        mouse: Any | None = None,
        keyboard: Any | None = None,
    ) -> None:
        self.config = config
        self.clock = clock
        self.mouse = mouse or (
            RecordingMouse() if config.dry_run else NativeWindowsMouse()
        )
        self.keyboard = keyboard or (
            RecordingKeyboard() if config.dry_run else NativeWindowsKeyboard()
        )
        self.recognizer = RobustGestureRecognizer()
        self.pose = PoseDebouncer(
            enter_frames=config.pose_enter_frames,
            release_frames=config.pose_release_frames,
        )
        self.arm_hold = HoldDetector(config.arm_hold_seconds)
        self.disarm_hold = HoldDetector(config.disarm_hold_seconds)
        self.index_pinch = PinchLatch(
            enter_ratio=config.pinch_enter_ratio,
            release_ratio=config.pinch_release_ratio,
            cooldown_seconds=config.click_cooldown_seconds,
            enter_frames=config.pinch_enter_frames,
            release_frames=config.pinch_release_frames,
        )
        self.middle_pinch = PinchLatch(
            enter_ratio=config.middle_pinch_enter_ratio,
            release_ratio=config.middle_pinch_release_ratio,
            cooldown_seconds=config.click_cooldown_seconds,
            enter_frames=config.pinch_enter_frames,
            release_frames=config.pinch_release_frames,
        )
        self.ring_pinch = PinchLatch(
            enter_ratio=config.ring_pinch_enter_ratio,
            release_ratio=config.ring_pinch_release_ratio,
            cooldown_seconds=max(0.65, config.click_cooldown_seconds),
            enter_frames=config.pinch_enter_frames,
            release_frames=config.pinch_release_frames,
        )
        # Backwards-compatible alias used by the Phase 1 tests.
        self.pinch = self.index_pinch
        self.pointer = RelativePointerController(
            sensitivity_x=config.pointer_sensitivity_x,
            sensitivity_y=config.pointer_sensitivity_y,
            minimum_alpha=config.pointer_min_alpha,
            maximum_alpha=config.pointer_max_alpha,
            speed_reference_pixels=config.pointer_speed_reference_pixels,
            maximum_step_pixels=config.pointer_max_step_pixels,
            dead_zone_pixels=config.pointer_dead_zone_pixels,
        )
        self.scroll = ScrollController(
            dead_zone=config.scroll_dead_zone,
            scale=config.scroll_scale,
            maximum_notches=config.scroll_maximum_notches,
        )
        self.swipe = OpenPalmSwipeDetector(
            minimum_horizontal_distance=config.swipe_min_horizontal_ratio,
            maximum_vertical_distance=config.swipe_max_vertical_ratio,
            maximum_duration_seconds=config.swipe_max_duration_seconds,
            cooldown_seconds=config.swipe_cooldown_seconds,
        )
        self.armed = False
        self.armed_at: float | None = None
        self.last_valid_hand_at: float | None = None
        self.status_message = (
            "WAITING: show one hand to start automatically."
            if config.simple_mode
            else "Show an open palm to arm."
        )
        self._last_console_status = ""
        self._index_press_started_at: float | None = None
        self._dragging = False
        self._swipe_ready = False
        self._simple_arm_started_at: float | None = None
        self._emergency_paused = False

    def _release_drag(self) -> None:
        if self._dragging:
            self.mouse.left_up()
        self._dragging = False
        self._index_press_started_at = None

    def _set_armed(self, armed: bool, timestamp: float) -> None:
        if self.armed == armed:
            return
        if not armed:
            self._release_drag()
        self.armed = armed
        self.armed_at = timestamp if armed else None
        self.pointer.reset()
        self.scroll.reset()
        self.swipe.reset_pose()
        self._swipe_ready = armed and not self.config.simple_mode
        self.index_pinch.reset()
        self.middle_pinch.reset()
        self.ring_pinch.reset()
        self._simple_arm_started_at = None
        if self.config.simple_mode:
            self.status_message = (
                "READY: point to move, pinch to click/drag, or show two fingers to scroll."
                if armed
                else "WAITING: show one hand to start automatically."
            )
        else:
            self.status_message = (
                "ARMED: keep the palm open and move it left or right."
                if armed
                else "SAFE: show an open palm to arm."
            )
        print(self.status_message)

    def emergency_stop(self, timestamp: float) -> None:
        if self.config.simple_mode:
            self._emergency_paused = not self._emergency_paused
            self._set_armed(False, timestamp)
            self.status_message = (
                "EMERGENCY PAUSE: press Ctrl+Alt+G again to resume."
                if self._emergency_paused
                else "AUTO MODE RESUMED: show one hand to start."
            )
            print(self.status_message)
            return
        self._set_armed(False, timestamp)
        self.status_message = "EMERGENCY STOP: show an open palm to arm again."
        print(self.status_message)

    def process_observation(self, observation: Any) -> int:
        timestamp = observation.timestamp
        self.last_valid_hand_at = timestamp
        stable = self.pose.update(observation.gesture)

        if self.config.simple_mode:
            if self._emergency_paused:
                return 0
            if not self.armed:
                if stable not in {Gesture.NONE, Gesture.FIST}:
                    if self._simple_arm_started_at is None:
                        self._simple_arm_started_at = timestamp
                    elif (
                        timestamp - self._simple_arm_started_at
                        >= self.config.simple_auto_arm_seconds
                    ):
                        self._set_armed(True, timestamp)
                else:
                    self._simple_arm_started_at = None
                self.disarm_hold.reset()
                return 0
            self._simple_arm_started_at = None
            self.arm_hold.reset()
            if self.disarm_hold.update(stable, Gesture.FIST, timestamp):
                self._set_armed(False, timestamp)
                self.status_message = "PAUSED: show one hand to start again."
                return 0
        else:
            if not self.armed:
                if self.arm_hold.update(stable, Gesture.OPEN_PALM, timestamp):
                    self._set_armed(True, timestamp)
                self.disarm_hold.reset()
                return 0

            self.arm_hold.reset()
            if self.disarm_hold.update(stable, Gesture.FIST, timestamp):
                self._set_armed(False, timestamp)
                return 0

        if (
            self.armed_at is not None
            and timestamp - self.armed_at < self.config.action_warmup_seconds
        ):
            return 0

        actions = 0
        if not self.config.simple_mode:
            if stable != Gesture.OPEN_PALM:
                self._swipe_ready = True
                self.swipe.reset_pose()
            elif self._swipe_ready:
                direction = self.swipe.update(observation.palm_center, timestamp)
                if direction == "left":
                    self.keyboard.browser_back()
                    self.status_message = "SWIPE LEFT: browser back."
                    actions += 1
                elif direction == "right":
                    self.keyboard.browser_forward()
                    self.status_message = "SWIPE RIGHT: browser forward."
                    actions += 1
            else:
                self.swipe.reset_pose()
        else:
            self._swipe_ready = False
            self.swipe.reset_pose()

        pinch_ratios = {
            "index": float(observation.metrics.get("index_pinch", 99.0)),
            "middle": float(observation.metrics.get("middle_pinch", 99.0)),
            "ring": float(observation.metrics.get("ring_pinch", 99.0)),
        }
        selected_name = min(pinch_ratios, key=pinch_ratios.get)
        selected_ratio = pinch_ratios[selected_name]
        thresholds = {
            "index": self.config.pinch_enter_ratio,
            "middle": self.config.middle_pinch_enter_ratio,
            "ring": self.config.ring_pinch_enter_ratio,
        }
        selected_name = (
            selected_name if selected_ratio <= thresholds[selected_name] else None
        )
        # Index pinch supports both a normal click and drag-and-drop.
        index_ratio = pinch_ratios["index"] if selected_name == "index" else 99.0
        index_was_active = self.index_pinch.active
        index_started = self.index_pinch.update(index_ratio, timestamp)
        if index_started:
            self._index_press_started_at = timestamp
        if (
            self.index_pinch.active
            and not self._dragging
            and self._index_press_started_at is not None
            and timestamp - self._index_press_started_at >= self.config.drag_hold_seconds
        ):
            self.mouse.left_down()
            self._dragging = True
            actions += 1
        if index_was_active and not self.index_pinch.active:
            if self._dragging:
                self.mouse.left_up()
                self._dragging = False
            else:
                self.mouse.left_click()
            self._index_press_started_at = None
            actions += 1

        pinch_actions = {
            "middle": (self.middle_pinch, self.mouse.right_click),
            "ring": (self.ring_pinch, self.mouse.double_click),
        }
        for name, (latch, action) in pinch_actions.items():
            ratio = pinch_ratios[name] if selected_name == name else 99.0
            if latch.update(ratio, timestamp):
                action()
                self.pointer.reset()
                actions += 1

        if stable == Gesture.POINT:
            self.scroll.reset()
            target = self.pointer.update(
                observation.cursor_point,
                self.mouse.cursor_position(),
                self.mouse.screen_size(),
            )
            if target != self.mouse.cursor_position():
                self.mouse.move(*target)
                actions += 1
        elif stable == Gesture.TWO_FINGER:
            self.pointer.reset()
            amount = self.scroll.update(
                float(observation.metrics.get("scroll_y", observation.palm_center.y))
            )
            if amount:
                self.mouse.scroll(amount)
                actions += 1
        else:
            self.pointer.reset()
            self.scroll.reset()
        return actions

    def process_no_hand(self, timestamp: float) -> None:
        self._release_drag()
        self.pose.update(Gesture.NONE)
        self.pointer.reset()
        self.scroll.reset()
        self.swipe.reset_pose()
        # In standard mode, the next open palm can start a swipe immediately.
        # Simple mode keeps browser swipes disabled.
        self._swipe_ready = self.armed and not self.config.simple_mode
        self._simple_arm_started_at = None
        self.index_pinch.reset()
        self.middle_pinch.reset()
        self.ring_pinch.reset()
        self.arm_hold.reset()
        self.disarm_hold.reset()
        no_hand_timeout = (
            self.config.simple_no_hand_disarm_seconds
            if self.config.simple_mode
            else self.config.no_hand_disarm_seconds
        )
        if (
            self.armed
            and self.last_valid_hand_at is not None
            and timestamp - self.last_valid_hand_at >= no_hand_timeout
        ):
            self._set_armed(False, timestamp)
            self.status_message = (
                "No hand detected; show one hand to start again."
                if self.config.simple_mode
                else "No hand detected; control safely disarmed."
            )

    def run(self) -> StableGestureSummary:
        try:
            import cv2
            import mediapipe as mp
        except Exception as exc:
            raise RuntimeError(
                "Stable gestures require OpenCV and MediaPipe. Run "
                "SETUP_HAND_GESTURES.cmd from the Mama-AI folder."
            ) from exc
        if not hasattr(mp, "solutions"):
            raise RuntimeError(
                "This stable mode requires mediapipe==0.10.21. Run "
                "SETUP_HAND_GESTURES.cmd again."
            )

        capture = LatestFrameCapture(cv2, self.config).start()
        capture.wait_until_ready()
        hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1 if self.config.simple_mode else 2,
            model_complexity=self.config.model_complexity,
            min_detection_confidence=self.config.minimum_detection_confidence,
            min_tracking_confidence=self.config.minimum_tracking_confidence,
        )
        emergency = WindowsEmergencyHotkey()
        sequence = 0
        frames = 0
        valid = 0
        actions = 0
        exit_reason = "stopped"
        fps = 0.0
        fps_started = self.clock()
        fps_frames = 0
        if self.config.simple_mode:
            print("Simple finger mode started.")
            print("Show one hand: auto start | Point: move | Pinches: clicks/drag | Two fingers: scroll | Fist: pause")
        else:
            print("Stable gesture mode started.")
            print("Open palm: arm, then move left/right to swipe | Fist: disarm | Pinches: click/drag")
        try:
            while True:
                timestamp = self.clock()
                if emergency.poll():
                    self.emergency_stop(timestamp)
                sequence, image = capture.latest(sequence)
                if image is None:
                    # No newer camera frame is available yet. Do not treat this
                    # brief interval as a lost hand; doing so would reset pose
                    # stability between normal 30 FPS frames.
                    time.sleep(0.001)
                    continue

                frames += 1
                fps_frames += 1
                elapsed = timestamp - fps_started
                if elapsed >= 0.75:
                    fps = fps_frames / elapsed
                    fps_frames = 0
                    fps_started = timestamp

                image = cv2.flip(image, 1)
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                result = hands.process(rgb)
                rgb.flags.writeable = True
                gesture = Gesture.NONE
                index_tip: Point3D | None = None
                observation: GestureObservation | None = None
                landmarks_for_preview: Any | None = None

                hand_count = len(result.multi_hand_landmarks or [])
                if hand_count == 1:
                    landmarks = result.multi_hand_landmarks[0]
                    landmarks_for_preview = landmarks
                    confidence = 1.0
                    handedness = "unknown"
                    if result.multi_handedness:
                        classification = result.multi_handedness[0].classification[0]
                        confidence = float(classification.score)
                        handedness = str(classification.label).lower()
                    height, width = image.shape[:2]
                    frame = HandFrame(
                        landmarks=tuple(
                            Point3D(float(p.x), float(p.y), float(p.z))
                            for p in landmarks.landmark
                        ),
                        timestamp=timestamp,
                        confidence=confidence,
                        handedness=handedness,
                        source_width=int(width),
                        source_height=int(height),
                    )
                    observation = self.recognizer.recognize(frame)
                    gesture = observation.gesture
                    index_tip = observation.cursor_point
                    if observation.confidence >= self.config.minimum_frame_confidence:
                        valid += 1
                        actions += self.process_observation(observation)
                    else:
                        self.process_no_hand(timestamp)
                else:
                    self.process_no_hand(timestamp)
                    if hand_count > 1:
                        self.status_message = "Use only one hand."

                stable_name = self.pose.stable.value
                if self.config.simple_mode:
                    status = (
                        "PAUSED"
                        if self._emergency_paused
                        else ("READY" if self.armed else "WAITING")
                    )
                else:
                    status = "ARMED" if self.armed else "SAFE"
                console_status = f"{status} gesture={stable_name} fps={fps:.1f}"
                if console_status != self._last_console_status and not self.config.preview_enabled:
                    print(console_status)
                    self._last_console_status = console_status

                if self.config.preview_enabled:
                    if self.config.simple_mode and landmarks_for_preview is not None:
                        mp.solutions.drawing_utils.draw_landmarks(
                            image,
                            landmarks_for_preview,
                            mp.solutions.hands.HAND_CONNECTIONS,
                        )
                        fingertip_specs = (
                            (4, "T", (255, 0, 255)),
                            (8, "I", (0, 255, 255)),
                            (12, "M", (255, 255, 0)),
                            (16, "R", (0, 165, 255)),
                            (20, "P", (255, 100, 100)),
                        )
                        for tip_index, label, tip_colour in fingertip_specs:
                            point = landmarks_for_preview.landmark[tip_index]
                            x = int(point.x * image.shape[1])
                            y = int(point.y * image.shape[0])
                            radius = 8 if label == "I" else 6
                            cv2.circle(image, (x, y), radius, tip_colour, -1)
                            cv2.putText(
                                image,
                                label,
                                (x + 7, y - 7),
                                cv2.FONT_HERSHEY_SIMPLEX,
                                0.42,
                                tip_colour,
                                1,
                            )
                    elif index_tip is not None:
                        cv2.circle(
                            image,
                            (
                                int(index_tip.x * image.shape[1]),
                                int(index_tip.y * image.shape[0]),
                            ),
                            7,
                            (0, 255, 255),
                            -1,
                        )
                    colour = (0, 200, 0) if self.armed else (0, 180, 255)
                    mode_name = "Simple Finger Mode" if self.config.simple_mode else "Stable Gestures"
                    cv2.putText(
                        image,
                        f"Mama AI {mode_name}: {status}",
                        (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        colour,
                        2,
                    )
                    cv2.putText(
                        image,
                        (
                            f"Gesture: {stable_name} | FPS: {fps:.1f} | "
                            f"I:{float(observation.metrics.get('index_pinch', 9.9)):.2f} "
                            f"M:{float(observation.metrics.get('middle_pinch', 9.9)):.2f} "
                            f"R:{float(observation.metrics.get('ring_pinch', 9.9)):.2f}"
                            if hand_count == 1 and observation is not None
                            else f"Gesture: {stable_name} | FPS: {fps:.1f}"
                        ),
                        (10, 48),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.48,
                        (255, 255, 255),
                        1,
                    )
                    instruction = (
                        "Point=move  Index pinch=click/drag  Two fingers=scroll  Fist=pause"
                        if self.config.simple_mode
                        else "Palm: hold to arm, then move L/R  Index=click/drag  Middle=right  Ring=double"
                    )
                    cv2.putText(
                        image,
                        instruction,
                        (10, 70),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.42,
                        (255, 255, 255),
                        1,
                    )
                    cv2.putText(
                        image,
                        self.status_message[:64],
                        (10, 92),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.39,
                        (0, 230, 230),
                        1,
                    )
                    cv2.imshow("Mama AI Stable Hand Gestures", image)
                    key = cv2.waitKey(1) & 0xFF
                    if key in {ord("q"), 27}:
                        exit_reason = "preview_exit"
                        break
        except KeyboardInterrupt:
            exit_reason = "keyboard_interrupt"
        finally:
            self._set_armed(False, self.clock())
            hands.close()
            capture.close()
            cv2.destroyAllWindows()

        return StableGestureSummary(
            frames=frames,
            valid_hand_frames=valid,
            actions=actions,
            exit_reason=exit_reason,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mama AI low-latency Windows hand gestures"
    )
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-preview", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = StableGestureConfig(
        camera_index=args.camera,
        dry_run=args.dry_run,
        preview_enabled=not args.no_preview,
        simple_mode=False,
    )
    summary = StableGestureAgent(config).run()
    print(
        "Stable gestures stopped: "
        f"frames={summary.frames}, valid={summary.valid_hand_frames}, "
        f"actions={summary.actions}, reason={summary.exit_reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
