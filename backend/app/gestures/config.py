"""Configuration for the native Mama AI hand-gesture agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import BASE_DIR


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw.strip())
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw.strip())
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    value = Path(raw).expanduser() if raw else default
    if not value.is_absolute():
        value = BASE_DIR / value
    return value.resolve()


@dataclass(frozen=True)
class GestureAgentConfig:
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    camera_buffer_size: int = 1
    model_complexity: int = 0
    profile_name: str = "default"
    profiles_directory: Path = BASE_DIR / "gesture_profiles"
    preview_enabled: bool = True
    mirror_camera: bool = True
    maximum_hands: int = 1
    minimum_detection_confidence: float = 0.60
    minimum_tracking_confidence: float = 0.60
    minimum_frame_confidence: float = 0.45
    stable_enter_frames: int = 3
    stable_release_frames: int = 2
    arm_hold_ms: int = 1000
    arm_release_ms: int = 350
    arm_toggle_cooldown_ms: int = 1800
    stale_frame_timeout_ms: int = 2500
    cursor_smoothing_alpha: float = 0.18
    cursor_margin: float = 0.16
    cursor_maximum_step_pixels: float = 85.0
    scroll_dead_zone: float = 0.010
    scroll_scale: float = 240.0
    scroll_smoothing_alpha: float = 0.35
    scroll_maximum_step: int = 18
    swipe_window_ms: int = 450
    swipe_minimum_distance: float = 0.20
    swipe_maximum_cross_axis: float = 0.14
    window_poll_interval_ms: int = 250
    action_pause_seconds: float = 0.0
    dry_run: bool = False
    auto_select_profiles: bool = True

    def __post_init__(self) -> None:
        if self.camera_index < 0:
            raise ValueError("camera_index must not be negative.")
        if not self.profile_name.strip():
            raise ValueError("profile_name must not be empty.")
        if self.maximum_hands != 1:
            raise ValueError("Phase 1 supports exactly one tracked hand.")
        if self.model_complexity not in {0, 1}:
            raise ValueError("model_complexity must be 0 or 1.")
        for name, value in (
            ("minimum_detection_confidence", self.minimum_detection_confidence),
            ("minimum_tracking_confidence", self.minimum_tracking_confidence),
            ("minimum_frame_confidence", self.minimum_frame_confidence),
            ("cursor_smoothing_alpha", self.cursor_smoothing_alpha),
            ("scroll_smoothing_alpha", self.scroll_smoothing_alpha),
        ):
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be greater than 0 and at most 1.")
        if not 0.0 <= self.cursor_margin < 0.45:
            raise ValueError("cursor_margin must be between 0 and 0.45.")
        for name, value in (
            ("camera_width", self.camera_width),
            ("camera_height", self.camera_height),
            ("camera_fps", self.camera_fps),
            ("camera_buffer_size", self.camera_buffer_size),
            ("stable_enter_frames", self.stable_enter_frames),
            ("stable_release_frames", self.stable_release_frames),
            ("arm_hold_ms", self.arm_hold_ms),
            ("arm_release_ms", self.arm_release_ms),
            ("arm_toggle_cooldown_ms", self.arm_toggle_cooldown_ms),
            ("stale_frame_timeout_ms", self.stale_frame_timeout_ms),
            ("scroll_maximum_step", self.scroll_maximum_step),
            ("swipe_window_ms", self.swipe_window_ms),
            ("window_poll_interval_ms", self.window_poll_interval_ms),
        ):
            if value < 1:
                raise ValueError(f"{name} must be positive.")
        if self.action_pause_seconds < 0:
            raise ValueError("action_pause_seconds must not be negative.")

    @classmethod
    def from_environment(cls) -> "GestureAgentConfig":
        return cls(
            camera_index=_env_int("MAMA_GESTURE_CAMERA_INDEX", 0),
            camera_width=_env_int("MAMA_GESTURE_CAMERA_WIDTH", 640, 160),
            camera_height=_env_int("MAMA_GESTURE_CAMERA_HEIGHT", 480, 120),
            camera_fps=_env_int("MAMA_GESTURE_CAMERA_FPS", 30, 1),
            camera_buffer_size=_env_int(
                "MAMA_GESTURE_CAMERA_BUFFER_SIZE", 1, 1
            ),
            model_complexity=_env_int("MAMA_GESTURE_MODEL_COMPLEXITY", 0),
            profile_name=os.getenv("MAMA_GESTURE_PROFILE", "default").strip()
            or "default",
            profiles_directory=_env_path(
                "MAMA_GESTURE_PROFILES_DIR",
                BASE_DIR / "gesture_profiles",
            ),
            preview_enabled=_env_bool("MAMA_GESTURE_PREVIEW", True),
            mirror_camera=_env_bool("MAMA_GESTURE_MIRROR_CAMERA", True),
            minimum_detection_confidence=_env_float(
                "MAMA_GESTURE_MIN_DETECTION_CONFIDENCE", 0.60
            ),
            minimum_tracking_confidence=_env_float(
                "MAMA_GESTURE_MIN_TRACKING_CONFIDENCE", 0.60
            ),
            minimum_frame_confidence=_env_float(
                "MAMA_GESTURE_MIN_FRAME_CONFIDENCE", 0.45
            ),
            stable_enter_frames=_env_int(
                "MAMA_GESTURE_STABLE_ENTER_FRAMES", 3, 1
            ),
            stable_release_frames=_env_int(
                "MAMA_GESTURE_STABLE_RELEASE_FRAMES", 2, 1
            ),
            arm_hold_ms=_env_int("MAMA_GESTURE_ARM_HOLD_MS", 1000, 1),
            arm_release_ms=_env_int("MAMA_GESTURE_ARM_RELEASE_MS", 350, 1),
            arm_toggle_cooldown_ms=_env_int(
                "MAMA_GESTURE_ARM_TOGGLE_COOLDOWN_MS", 1800, 1
            ),
            stale_frame_timeout_ms=_env_int(
                "MAMA_GESTURE_STALE_FRAME_TIMEOUT_MS", 2500, 1
            ),
            cursor_smoothing_alpha=_env_float(
                "MAMA_GESTURE_CURSOR_SMOOTHING_ALPHA", 0.18
            ),
            cursor_margin=_env_float("MAMA_GESTURE_CURSOR_MARGIN", 0.16),
            cursor_maximum_step_pixels=_env_float(
                "MAMA_GESTURE_CURSOR_MAX_STEP_PIXELS", 85.0, 1.0
            ),
            scroll_dead_zone=_env_float(
                "MAMA_GESTURE_SCROLL_DEAD_ZONE", 0.010
            ),
            scroll_scale=_env_float("MAMA_GESTURE_SCROLL_SCALE", 240.0, 1.0),
            scroll_smoothing_alpha=_env_float(
                "MAMA_GESTURE_SCROLL_SMOOTHING_ALPHA", 0.35
            ),
            scroll_maximum_step=_env_int(
                "MAMA_GESTURE_SCROLL_MAX_STEP", 18, 1
            ),
            swipe_window_ms=_env_int("MAMA_GESTURE_SWIPE_WINDOW_MS", 450, 1),
            swipe_minimum_distance=_env_float(
                "MAMA_GESTURE_SWIPE_MIN_DISTANCE", 0.20, 0.01
            ),
            swipe_maximum_cross_axis=_env_float(
                "MAMA_GESTURE_SWIPE_MAX_CROSS_AXIS", 0.14, 0.01
            ),
            window_poll_interval_ms=_env_int(
                "MAMA_GESTURE_WINDOW_POLL_INTERVAL_MS", 250, 1
            ),
            action_pause_seconds=_env_float(
                "MAMA_GESTURE_ACTION_PAUSE_SECONDS", 0.0
            ),
            dry_run=_env_bool("MAMA_GESTURE_DRY_RUN", False),
            auto_select_profiles=_env_bool(
                "MAMA_GESTURE_AUTO_SELECT_PROFILES", True
            ),
        )
