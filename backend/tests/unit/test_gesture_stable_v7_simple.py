from pathlib import Path
from types import SimpleNamespace
import unittest

from app.gestures.models import Gesture, Point3D
from app.gestures.stable_agent import (
    RecordingKeyboard,
    RecordingMouse,
    StableGestureAgent,
    StableGestureConfig,
)


class StableGestureV7SimpleModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mouse = RecordingMouse()
        self.keyboard = RecordingKeyboard()
        self.agent = StableGestureAgent(
            StableGestureConfig(
                dry_run=True,
                preview_enabled=False,
                simple_mode=True,
                pose_enter_frames=1,
                simple_auto_arm_seconds=0.10,
                simple_no_hand_disarm_seconds=2.0,
                action_warmup_seconds=0.0,
                disarm_hold_seconds=0.50,
            ),
            mouse=self.mouse,
            keyboard=self.keyboard,
        )

    @staticmethod
    def observation(
        gesture: Gesture,
        timestamp: float,
        x: float = 0.50,
        y: float = 0.50,
    ) -> SimpleNamespace:
        point = Point3D(x, y, 0.0)
        return SimpleNamespace(
            gesture=gesture,
            timestamp=timestamp,
            confidence=1.0,
            cursor_point=point,
            palm_center=point,
            palm_scale=0.20,
            extended_fingers=(True, False, False, False),
            metrics={
                "index_pinch": 99.0,
                "middle_pinch": 99.0,
                "ring_pinch": 99.0,
                "scroll_y": y,
            },
        )

    def test_any_clear_non_fist_pose_auto_arms(self) -> None:
        self.agent.process_observation(self.observation(Gesture.POINT, 1.00))
        self.assertFalse(self.agent.armed)
        self.agent.process_observation(self.observation(Gesture.POINT, 1.11))
        self.assertTrue(self.agent.armed)

    def test_open_palm_does_not_trigger_browser_swipe_in_simple_mode(self) -> None:
        self.agent.armed = True
        self.agent.armed_at = 0.0
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.00, 0.75)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.25, 0.25)
        )
        self.assertEqual(self.keyboard.calls, [])

    def test_fist_pauses_simple_mode(self) -> None:
        self.agent.armed = True
        self.agent.armed_at = 0.0
        self.agent.process_observation(self.observation(Gesture.FIST, 1.00))
        self.agent.process_observation(self.observation(Gesture.FIST, 1.55))
        self.assertFalse(self.agent.armed)

    def test_no_hand_disarms_after_simple_timeout(self) -> None:
        self.agent.armed = True
        self.agent.armed_at = 0.0
        self.agent.last_valid_hand_at = 1.0
        self.agent.process_no_hand(3.01)
        self.assertFalse(self.agent.armed)

    def test_emergency_hotkey_toggles_pause_and_resume(self) -> None:
        self.agent.armed = True
        self.agent.armed_at = 0.0
        self.agent.emergency_stop(1.0)
        self.assertTrue(self.agent._emergency_paused)
        self.assertFalse(self.agent.armed)
        self.agent.emergency_stop(2.0)
        self.assertFalse(self.agent._emergency_paused)

    def test_preview_tracks_all_five_fingertips(self) -> None:
        backend = Path(__file__).resolve().parents[2]
        source = (backend / "app" / "gestures" / "stable_agent.py").read_text(
            encoding="utf-8"
        )
        for marker in ('(4, "T"', '(8, "I"', '(12, "M"', '(16, "R"', '(20, "P"'):
            self.assertIn(marker, source)
        self.assertIn("HAND_CONNECTIONS", source)


if __name__ == "__main__":
    unittest.main()
