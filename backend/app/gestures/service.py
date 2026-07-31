"""Native foreground service for the Windows hand-gesture agent."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from app.gestures.config import GestureAgentConfig
from app.gestures.dispatcher import (
    ActionDispatcher,
    PyAutoGUIActionSink,
    RecordingActionSink,
)
from app.gestures.engine import GestureEngine
from app.gestures.mediapipe_adapter import MediaPipeHandCamera
from app.gestures.models import EngineEvent, EngineEventType
from app.gestures.profiles import ProfileRegistry
from app.gestures.window_context import (
    WindowsEmergencyHotkey,
    foreground_window_title,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GestureAgentSummary:
    frames: int
    valid_hand_frames: int
    dispatched_actions: int
    emergency_stops: int
    exit_reason: str


class GestureAgent:
    def __init__(
        self,
        config: GestureAgentConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.clock = clock
        profiles = ProfileRegistry.from_directory(config.profiles_directory)
        profiles.get(config.profile_name)
        sink = (
            RecordingActionSink()
            if config.dry_run
            else PyAutoGUIActionSink(config.action_pause_seconds)
        )
        self.dispatcher = ActionDispatcher(sink)
        self.engine = GestureEngine(
            config=config,
            profiles=profiles,
            dispatcher=self.dispatcher,
        )
        self.camera = MediaPipeHandCamera(config)
        self.emergency_hotkey = WindowsEmergencyHotkey()

    def _log_event(self, event: EngineEvent) -> None:
        if event.type == EngineEventType.OBSERVATION:
            return
        LOGGER.info(
            "%s gesture=%s profile=%s message=%s",
            event.type.value,
            event.gesture.value,
            event.profile,
            event.message,
        )

    def run(self) -> GestureAgentSummary:
        frames = 0
        valid = 0
        actions = 0
        emergency_stops = 0
        exit_reason = "stopped"
        last_message = "Hold three fingers to arm."
        last_external_window_title = ""
        next_window_poll_at = 0.0
        try:
            while True:
                timestamp = self.clock()
                if self.emergency_hotkey.poll():
                    emergency_stops += 1
                    for event in self.engine.emergency_stop(timestamp):
                        self._log_event(event)
                        last_message = event.message
                result = self.camera.read(timestamp)
                frames += 1
                events: list[EngineEvent] = []
                if result.frame is not None:
                    valid += 1
                    if timestamp >= next_window_poll_at:
                        window_title = foreground_window_title()
                        if (
                            window_title
                            and "mama ai hand gestures"
                            not in window_title.lower()
                        ):
                            last_external_window_title = window_title
                        next_window_poll_at = timestamp + (
                            self.config.window_poll_interval_ms / 1000.0
                        )
                    events = self.engine.process_frame(
                        result.frame,
                        window_title=last_external_window_title,
                    )
                else:
                    events = self.engine.tick(timestamp)
                for event in events:
                    self._log_event(event)
                    if event.type == EngineEventType.ACTION:
                        actions += 1
                    if event.type != EngineEventType.OBSERVATION:
                        last_message = event.message
                if self.config.preview_enabled:
                    image = self.camera.annotate(
                        result,
                        gesture=self.engine.state.last_gesture.value,
                        armed=self.engine.safety.armed,
                        profile=self.engine.state.active_profile,
                        message=last_message,
                    )
                    if not self.camera.show(image):
                        exit_reason = "preview_exit"
                        break
        except KeyboardInterrupt:
            exit_reason = "keyboard_interrupt"
        except Exception:
            exit_reason = "error"
            LOGGER.exception("Gesture agent stopped after an unrecoverable error.")
        finally:
            self.engine.emergency_stop(self.clock())
            self.camera.close()
        return GestureAgentSummary(
            frames=frames,
            valid_hand_frames=valid,
            dispatched_actions=actions,
            emergency_stops=emergency_stops,
            exit_reason=exit_reason,
        )
