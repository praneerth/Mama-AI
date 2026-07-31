"""Dependency-free orchestration for safe hand-gesture desktop control."""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.gestures.config import GestureAgentConfig
from app.gestures.dispatcher import ActionDispatcher
from app.gestures.geometry import CursorMapper, ExponentialPointSmoother
from app.gestures.models import (
    ActionSpec,
    EngineEvent,
    EngineEventType,
    Gesture,
    GestureObservation,
    HandFrame,
    Point3D,
)
from app.gestures.profiles import ProfileRegistry
from app.gestures.recognizer import GestureRecognizer
from app.gestures.safety import GestureSafetyController
from app.gestures.stability import (
    CooldownRegistry,
    GestureLatch,
    GestureStabilizer,
    ScrollTracker,
    SwipeDetector,
)


@dataclass
class GestureEngineState:
    active_profile: str = ""
    last_gesture: Gesture = Gesture.NONE
    last_raw_gesture: Gesture = Gesture.NONE
    last_observation_at: float | None = None


class GestureEngine:
    def __init__(
        self,
        *,
        config: GestureAgentConfig,
        profiles: ProfileRegistry,
        dispatcher: ActionDispatcher,
        recognizer: GestureRecognizer | None = None,
        safety: GestureSafetyController | None = None,
    ) -> None:
        self.config = config
        self.profiles = profiles
        self.dispatcher = dispatcher
        self.recognizer = recognizer or GestureRecognizer()
        self.safety = safety or GestureSafetyController(
            stale_frame_timeout_ms=config.stale_frame_timeout_ms,
            arm_toggle_cooldown_ms=config.arm_toggle_cooldown_ms,
        )
        self.state = GestureEngineState(active_profile=config.profile_name)
        self._gesture_stabilizer = GestureStabilizer(
            enter_frames=config.stable_enter_frames,
            release_frames=config.stable_release_frames,
        )
        self._arm_latch = GestureLatch()
        self._arm_needs_release = False
        self._arm_release_started_at: float | None = None
        self._action_latch = GestureLatch()
        self._cooldowns = CooldownRegistry()
        self._scroll = ScrollTracker(
            dead_zone=config.scroll_dead_zone,
            scale=config.scroll_scale,
            smoothing_alpha=config.scroll_smoothing_alpha,
            maximum_step=config.scroll_maximum_step,
        )
        self._swipe = SwipeDetector(
            window_ms=config.swipe_window_ms,
            minimum_distance=config.swipe_minimum_distance,
            maximum_cross_axis=config.swipe_maximum_cross_axis,
        )
        self._smoother = ExponentialPointSmoother(
            alpha=config.cursor_smoothing_alpha
        )
        self._cursor = CursorMapper(
            margin=config.cursor_margin,
            mirror_x=config.mirror_camera,
            maximum_step_pixels=config.cursor_maximum_step_pixels,
        )

    def _reset_motion(self) -> None:
        self._action_latch.reset()
        self._scroll.reset()
        self._swipe.reset()
        self._smoother.reset()
        self._cursor.reset()

    def _release_and_reset(self) -> None:
        self.dispatcher.release_all()
        self._reset_motion()

    def emergency_stop(self, timestamp: float) -> list[EngineEvent]:
        changed = self.safety.emergency_stop()
        self._release_and_reset()
        if not changed:
            return []
        return [
            EngineEvent(
                type=EngineEventType.DISARMED,
                timestamp=timestamp,
                message="Emergency stop latched; gesture actions disabled.",
                metadata={"emergency": True},
            )
        ]

    def reset_emergency(self, timestamp: float) -> list[EngineEvent]:
        self.safety.reset_emergency()
        self._release_and_reset()
        return [
            EngineEvent(
                type=EngineEventType.DISARMED,
                timestamp=timestamp,
                message="Emergency latch reset; hold three fingers to arm.",
                metadata={"emergency": False},
            )
        ]

    def tick(self, timestamp: float) -> list[EngineEvent]:
        if not self.safety.watchdog_expired(timestamp):
            return []
        self._release_and_reset()
        return [
            EngineEvent(
                type=EngineEventType.WATCHDOG,
                timestamp=timestamp,
                message="Valid hand frames stopped; gesture control disarmed.",
            )
        ]

    def _resolve_profile(
        self,
        window_title: str,
        timestamp: float,
    ) -> tuple[str, list[EngineEvent]]:
        profile = self.profiles.resolve(
            self.config.profile_name,
            window_title,
            auto_select=self.config.auto_select_profiles,
        )
        events: list[EngineEvent] = []
        if profile.name != self.state.active_profile:
            previous = self.state.active_profile
            self._release_and_reset()
            self.state.active_profile = profile.name
            events.append(
                EngineEvent(
                    type=EngineEventType.PROFILE_CHANGED,
                    timestamp=timestamp,
                    message=f"Gesture profile changed to {profile.name}.",
                    profile=profile.name,
                    metadata={"previous_profile": previous},
                )
            )
        return profile.name, events

    def _action_event(
        self,
        observation: GestureObservation,
        profile_name: str,
        spec: ActionSpec,
        dynamic: dict[str, object] | None = None,
    ) -> EngineEvent:
        command = self.dispatcher.dispatch(
            spec,
            gesture=observation.gesture,
            profile=profile_name,
            timestamp=observation.timestamp,
            dynamic=dynamic,
        )
        return EngineEvent(
            type=EngineEventType.ACTION,
            timestamp=observation.timestamp,
            message=f"Dispatched {command.action}.",
            gesture=observation.gesture,
            profile=profile_name,
            command=command,
        )

    def _toggle_arm(
        self,
        observation: GestureObservation,
    ) -> list[EngineEvent]:
        if self._arm_needs_release:
            if observation.gesture == Gesture.THREE_FINGER:
                self._arm_release_started_at = None
                return []
            if self._arm_release_started_at is None:
                self._arm_release_started_at = observation.timestamp
                return []
            released_ms = (
                observation.timestamp - self._arm_release_started_at
            ) * 1000.0
            if released_ms < self.config.arm_release_ms:
                return []
            self._arm_needs_release = False
            self._arm_release_started_at = None
            self._arm_latch.reset()

        if observation.gesture != Gesture.THREE_FINGER:
            self._arm_latch.update(Gesture.NONE, observation.timestamp, 0)
            return []
        if not self._arm_latch.update(
            Gesture.THREE_FINGER,
            observation.timestamp,
            self.config.arm_hold_ms,
        ):
            return []
        if not self.safety.toggle(observation.timestamp):
            return []

        # A deliberate release is required before the same pose can toggle
        # again. This prevents brief MediaPipe flicker from disarming control.
        self._arm_needs_release = True
        self._arm_release_started_at = None
        self._release_and_reset()
        event_type = (
            EngineEventType.ARMED
            if self.safety.armed
            else EngineEventType.DISARMED
        )
        return [
            EngineEvent(
                type=event_type,
                timestamp=observation.timestamp,
                message=(
                    "Gesture control armed."
                    if self.safety.armed
                    else "Gesture control disarmed."
                ),
                gesture=Gesture.THREE_FINGER,
                profile=self.state.active_profile,
            )
        ]

    def _continuous_action(
        self,
        observation: GestureObservation,
        profile_name: str,
        profile_actions: dict[Gesture, ActionSpec],
    ) -> list[EngineEvent]:
        events: list[EngineEvent] = []
        if observation.gesture == Gesture.POINT:
            self._scroll.reset()
            spec = profile_actions.get(Gesture.POINT)
            if spec and spec.action == "mouse.move":
                point = self._smoother.update(observation.cursor_point)
                width, height = self.dispatcher.sink.screen_size()
                x, y = self._cursor.map(point, width, height)
                events.append(
                    self._action_event(
                        observation,
                        profile_name,
                        spec,
                        {"x": x, "y": y},
                    )
                )
        elif observation.gesture == Gesture.TWO_FINGER:
            self._smoother.reset()
            spec = profile_actions.get(Gesture.TWO_FINGER)
            amount = self._scroll.update(observation.palm_center.y)
            if spec and spec.action == "mouse.scroll" and amount:
                events.append(
                    self._action_event(
                        observation,
                        profile_name,
                        spec,
                        {"amount": amount},
                    )
                )
        else:
            self._scroll.reset()
            self._smoother.reset()
        return events

    def _swipe_action(
        self,
        observation: GestureObservation,
        profile_name: str,
        profile_actions: dict[Gesture, ActionSpec],
    ) -> list[EngineEvent]:
        center = observation.palm_center
        if self.config.mirror_camera:
            center = Point3D(1.0 - center.x, center.y, center.z)
        swipe = self._swipe.update(
            center,
            observation.timestamp,
            enabled=observation.gesture == Gesture.OPEN_PALM,
        )
        if swipe == Gesture.NONE:
            return []
        spec = profile_actions.get(swipe)
        if spec is None:
            return []
        key = f"{profile_name}:{swipe.value}"
        if not self._cooldowns.ready(key, observation.timestamp, spec.cooldown_ms):
            return []
        self._cooldowns.mark(key, observation.timestamp)
        swipe_observation = GestureObservation(
            gesture=swipe,
            timestamp=observation.timestamp,
            confidence=observation.confidence,
            cursor_point=observation.cursor_point,
            palm_center=observation.palm_center,
            palm_scale=observation.palm_scale,
            extended_fingers=observation.extended_fingers,
            metrics=observation.metrics,
        )
        return [self._action_event(swipe_observation, profile_name, spec)]

    def _discrete_action(
        self,
        observation: GestureObservation,
        profile_name: str,
        profile_actions: dict[Gesture, ActionSpec],
    ) -> list[EngineEvent]:
        if observation.gesture in {
            Gesture.NONE,
            Gesture.POINT,
            Gesture.TWO_FINGER,
            Gesture.THREE_FINGER,
        }:
            self._action_latch.update(Gesture.NONE, observation.timestamp, 0)
            return []
        spec = profile_actions.get(observation.gesture)
        if spec is None:
            self._action_latch.update(Gesture.NONE, observation.timestamp, 0)
            return []
        if not self._action_latch.update(
            observation.gesture,
            observation.timestamp,
            spec.dwell_ms,
        ):
            return []
        key = f"{profile_name}:{observation.gesture.value}"
        if not self._cooldowns.ready(key, observation.timestamp, spec.cooldown_ms):
            return []
        self._cooldowns.mark(key, observation.timestamp)
        return [self._action_event(observation, profile_name, spec)]

    def process_frame(
        self,
        frame: HandFrame,
        *,
        window_title: str = "",
    ) -> list[EngineEvent]:
        raw_observation = self.recognizer.recognize(frame)
        self.state.last_raw_gesture = raw_observation.gesture
        self.state.last_observation_at = raw_observation.timestamp

        if raw_observation.confidence < self.config.minimum_frame_confidence:
            stable_gesture = self._gesture_stabilizer.update(Gesture.NONE)
            self.state.last_gesture = stable_gesture
            events = [
                EngineEvent(
                    type=EngineEventType.OBSERVATION,
                    timestamp=raw_observation.timestamp,
                    message=f"Observed {stable_gesture.value}.",
                    gesture=stable_gesture,
                    profile=self.state.active_profile,
                    metadata={
                        "confidence": raw_observation.confidence,
                        "raw_gesture": raw_observation.gesture.value,
                    },
                )
            ]
            events.extend(self.tick(raw_observation.timestamp))
            return events

        stable_gesture = self._gesture_stabilizer.update(
            raw_observation.gesture
        )
        observation = replace(raw_observation, gesture=stable_gesture)
        self.state.last_gesture = stable_gesture
        events = [
            EngineEvent(
                type=EngineEventType.OBSERVATION,
                timestamp=observation.timestamp,
                message=f"Observed {observation.gesture.value}.",
                gesture=observation.gesture,
                profile=self.state.active_profile,
                metadata={
                    "confidence": observation.confidence,
                    "raw_gesture": raw_observation.gesture.value,
                },
            )
        ]

        self.safety.observe_frame(observation.timestamp)
        profile_name, profile_events = self._resolve_profile(
            window_title,
            observation.timestamp,
        )
        events.extend(profile_events)
        events.extend(self._toggle_arm(observation))
        if not self.safety.actions_allowed:
            return events

        profile = self.profiles.get(profile_name)
        actions = dict(profile.actions)
        events.extend(self._continuous_action(observation, profile_name, actions))
        events.extend(self._swipe_action(observation, profile_name, actions))
        events.extend(self._discrete_action(observation, profile_name, actions))
        return events
