import unittest
from types import SimpleNamespace

from app.gestures.models import Gesture, Point3D
from app.gestures.stable_agent import (
    RecordingKeyboard,
    RecordingMouse,
    StableGestureAgent,
    StableGestureConfig,
)


class StableGestureV61PalmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mouse = RecordingMouse()
        self.keyboard = RecordingKeyboard()
        self.agent = StableGestureAgent(
            StableGestureConfig(
                dry_run=True,
                preview_enabled=False,
                pose_enter_frames=1,
                swipe_min_horizontal_ratio=0.14,
                swipe_max_vertical_ratio=0.28,
                swipe_max_duration_seconds=1.35,
                swipe_cooldown_seconds=0.85,
            ),
            mouse=self.mouse,
            keyboard=self.keyboard,
        )

    @staticmethod
    def observation(
        gesture: Gesture,
        timestamp: float,
        x: float,
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
            extended_fingers=(True, True, True, True),
            metrics={
                "index_pinch": 99.0,
                "middle_pinch": 99.0,
                "ring_pinch": 99.0,
                "scroll_y": y,
            },
        )

    def arm(self) -> None:
        self.agent.armed = True
        self.agent.armed_at = 0.0
        self.agent.last_valid_hand_at = 1.0

    def test_lowering_hand_while_armed_prepares_swipe(self) -> None:
        self.arm()
        self.agent.process_no_hand(1.10)
        self.assertTrue(self.agent._swipe_ready)

    def test_lower_hand_then_open_palm_swipe_left(self) -> None:
        self.arm()
        self.agent.process_no_hand(1.10)
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.20, 0.70)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.48, 0.53)
        )
        self.assertEqual(
            [name for name, _ in self.keyboard.calls].count("browser_back"),
            1,
        )

    def test_lowering_hand_while_safe_does_not_prepare_swipe(self) -> None:
        self.agent.armed = False
        self.agent.process_no_hand(1.10)
        self.assertFalse(self.agent._swipe_ready)


if __name__ == "__main__":
    unittest.main()
