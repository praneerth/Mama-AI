import unittest
from dataclasses import replace
from pathlib import Path

from app.gestures.config import GestureAgentConfig
from app.gestures.dispatcher import ActionDispatcher, RecordingActionSink
from app.gestures.engine import GestureEngine
from app.gestures.models import EngineEventType
from app.gestures.profiles import ProfileRegistry
from tests.unit.gesture_fixtures import make_hand_frame


class TestGestureEngine(unittest.TestCase):
    def setUp(self) -> None:
        profiles_directory = Path(__file__).resolve().parents[2] / "gesture_profiles"
        self.config = GestureAgentConfig(
            profiles_directory=profiles_directory,
            preview_enabled=False,
            arm_hold_ms=100,
            arm_toggle_cooldown_ms=100,
            stale_frame_timeout_ms=200,
            minimum_frame_confidence=0.5,
            stable_enter_frames=1,
            stable_release_frames=1,
            arm_release_ms=50,
            swipe_window_ms=500,
            swipe_minimum_distance=0.2,
            swipe_maximum_cross_axis=0.1,
        )
        self.sink = RecordingActionSink(width=1000, height=500)
        self.dispatcher = ActionDispatcher(self.sink)
        self.engine = GestureEngine(
            config=self.config,
            profiles=ProfileRegistry.from_directory(profiles_directory),
            dispatcher=self.dispatcher,
        )

    def arm(self, start: float = 0.0) -> None:
        arm_pose = (True, True, True, False)
        self.engine.process_frame(make_hand_frame(arm_pose, timestamp=start))
        events = self.engine.process_frame(
            make_hand_frame(arm_pose, timestamp=start + 0.11)
        )
        self.assertTrue(
            any(event.type == EngineEventType.ARMED for event in events)
        )
        self.assertTrue(self.engine.safety.armed)

    def test_starts_disarmed_and_three_finger_hold_arms(self) -> None:
        self.engine.process_frame(
            make_hand_frame((True, False, False, False), timestamp=0.0)
        )
        self.assertEqual(self.sink.calls, [])
        self.arm(1.0)

    def test_cursor_click_drag_release_and_watchdog(self) -> None:
        self.arm()
        self.engine.process_frame(
            make_hand_frame((True, False, False, False), timestamp=0.2)
        )
        self.assertEqual(self.sink.calls[0][0], "move")

        pinch = dict(
            extended=(True, False, False, False),
            pinch="index",
        )
        self.engine.process_frame(make_hand_frame(timestamp=0.3, **pinch))
        self.engine.process_frame(make_hand_frame(timestamp=0.40, **pinch))
        self.assertIn(("click", ("left", 1)), self.sink.calls)

        ring_pinch = dict(
            extended=(False, False, True, False),
            pinch="ring",
        )
        self.engine.process_frame(
            make_hand_frame(timestamp=0.42, **ring_pinch)
        )
        self.engine.process_frame(
            make_hand_frame(timestamp=0.55, **ring_pinch)
        )
        self.assertIn(("click", ("left", 2)), self.sink.calls)

        fist = (False, False, False, False)
        self.engine.process_frame(make_hand_frame(fist, timestamp=0.5))
        self.engine.process_frame(make_hand_frame(fist, timestamp=0.8))
        self.assertIn(("button_down", ("left",)), self.sink.calls)

        palm = (True, True, True, True)
        self.engine.process_frame(make_hand_frame(palm, timestamp=0.9))
        self.engine.process_frame(make_hand_frame(palm, timestamp=1.05))
        self.assertIn(("button_up", ("left",)), self.sink.calls)

        events = self.engine.tick(1.30)
        self.assertTrue(
            any(event.type == EngineEventType.WATCHDOG for event in events)
        )
        self.assertFalse(self.engine.safety.armed)

    def test_two_finger_scroll(self) -> None:
        self.arm()
        pose = (True, True, False, False)
        self.engine.process_frame(make_hand_frame(pose, timestamp=0.2))
        self.engine.process_frame(
            make_hand_frame(pose, timestamp=0.3, shift_y=-0.06)
        )
        scroll_calls = [call for call in self.sink.calls if call[0] == "scroll"]
        self.assertEqual(len(scroll_calls), 1)
        self.assertGreater(scroll_calls[0][1][0], 0)

    def test_browser_profile_and_swipe(self) -> None:
        self.arm()
        palm = (True, True, True, True)
        events = self.engine.process_frame(
            make_hand_frame(palm, timestamp=0.2),
            window_title="New Tab - Google Chrome",
        )
        self.assertTrue(
            any(event.type == EngineEventType.PROFILE_CHANGED for event in events)
        )
        self.engine.process_frame(
            make_hand_frame(palm, timestamp=0.4, shift_x=-0.30),
            window_title="New Tab - Google Chrome",
        )
        self.assertIn(("hotkey", ("ctrl", "tab")), self.sink.calls)

    def test_emergency_stop_releases_drag_and_blocks_actions(self) -> None:
        self.arm()
        fist = (False, False, False, False)
        self.engine.process_frame(make_hand_frame(fist, timestamp=0.2))
        self.engine.process_frame(make_hand_frame(fist, timestamp=0.5))
        self.assertIsNotNone(self.dispatcher.drag_button)
        events = self.engine.emergency_stop(0.6)
        self.assertTrue(events)
        self.assertIsNone(self.dispatcher.drag_button)
        count = len(self.sink.calls)
        self.engine.process_frame(
            make_hand_frame((True, False, False, False), timestamp=0.7)
        )
        self.assertEqual(len(self.sink.calls), count)


    def test_arm_pose_must_be_released_before_another_toggle(self) -> None:
        self.arm()
        arm_pose = (True, True, True, False)

        # Brief classification flicker must not allow the held arm pose to
        # toggle the controller off a second time.
        self.engine.process_frame(
            make_hand_frame((True, True, False, False), timestamp=0.12)
        )
        self.engine.process_frame(make_hand_frame(arm_pose, timestamp=0.18))
        self.engine.process_frame(make_hand_frame(arm_pose, timestamp=0.35))
        self.assertTrue(self.engine.safety.armed)

        # A deliberate non-arm pose held through arm_release_ms unlocks the
        # next toggle.
        point = (True, False, False, False)
        self.engine.process_frame(make_hand_frame(point, timestamp=0.40))
        self.engine.process_frame(make_hand_frame(point, timestamp=0.46))
        self.engine.process_frame(make_hand_frame(arm_pose, timestamp=0.60))
        events = self.engine.process_frame(
            make_hand_frame(arm_pose, timestamp=0.72)
        )
        self.assertTrue(
            any(event.type == EngineEventType.DISARMED for event in events)
        )
        self.assertFalse(self.engine.safety.armed)

    def test_low_confidence_frame_never_arms_or_dispatches(self) -> None:
        low_config = replace(self.config, minimum_frame_confidence=0.9)
        engine = GestureEngine(
            config=low_config,
            profiles=ProfileRegistry.from_directory(
                self.config.profiles_directory
            ),
            dispatcher=ActionDispatcher(RecordingActionSink()),
        )
        pose = (True, True, True, False)
        engine.process_frame(
            make_hand_frame(pose, timestamp=0.0, confidence=0.2)
        )
        engine.process_frame(
            make_hand_frame(pose, timestamp=0.2, confidence=0.2)
        )
        self.assertFalse(engine.safety.armed)

    def test_offline_game_profile_requires_explicit_selection(self) -> None:
        game_config = replace(
            self.config,
            profile_name="offline_game",
            auto_select_profiles=False,
        )
        sink = RecordingActionSink()
        engine = GestureEngine(
            config=game_config,
            profiles=ProfileRegistry.from_directory(
                self.config.profiles_directory
            ),
            dispatcher=ActionDispatcher(sink),
        )
        pose = (True, True, True, False)
        engine.process_frame(make_hand_frame(pose, timestamp=0.0))
        engine.process_frame(make_hand_frame(pose, timestamp=0.11))
        palm = (True, True, True, True)
        engine.process_frame(make_hand_frame(palm, timestamp=0.2))
        engine.process_frame(
            make_hand_frame(palm, timestamp=0.4, shift_y=-0.30)
        )
        self.assertIn(("press", ("up",)), sink.calls)
