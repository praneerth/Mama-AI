import unittest
from types import SimpleNamespace

from app.gestures.models import Gesture, Point3D
from app.gestures.stable_agent import (
    RecordingKeyboard,
    RecordingMouse,
    StableGestureAgent,
    StableGestureConfig,
)


class StableGestureV6SwipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mouse = RecordingMouse()
        self.keyboard = RecordingKeyboard()
        self.agent = StableGestureAgent(
            StableGestureConfig(
                dry_run=True,
                preview_enabled=False,
                pose_enter_frames=1,
                swipe_min_horizontal_ratio=0.18,
                swipe_max_vertical_ratio=0.20,
                swipe_max_duration_seconds=1.10,
                swipe_cooldown_seconds=0.85,
            ),
            mouse=self.mouse,
            keyboard=self.keyboard,
        )
        self.agent.armed = True
        self.agent.armed_at = 0.0

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

    def enable_swipe_after_arm_palm(self, timestamp: float = 1.0) -> None:
        self.agent.process_observation(
            self.observation(Gesture.POINT, timestamp, 0.50)
        )

    def test_open_palm_swipe_left_sends_browser_back(self) -> None:
        self.enable_swipe_after_arm_palm()
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.10, 0.70)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.35, 0.49)
        )
        self.assertEqual(
            [name for name, _ in self.keyboard.calls].count("browser_back"),
            1,
        )

    def test_open_palm_swipe_right_sends_browser_forward(self) -> None:
        self.enable_swipe_after_arm_palm()
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.10, 0.30)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.35, 0.51)
        )
        self.assertEqual(
            [name for name, _ in self.keyboard.calls].count("browser_forward"),
            1,
        )

    def test_arm_open_palm_cannot_accidentally_navigate(self) -> None:
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.10, 0.25)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.35, 0.75)
        )
        self.assertEqual(self.keyboard.calls, [])

    def test_vertical_open_palm_movement_is_not_a_swipe(self) -> None:
        self.enable_swipe_after_arm_palm()
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.10, 0.45, 0.25)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.35, 0.70, 0.55)
        )
        self.assertEqual(self.keyboard.calls, [])


if __name__ == "__main__":
    unittest.main()
