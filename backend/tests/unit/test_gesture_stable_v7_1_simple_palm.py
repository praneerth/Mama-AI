import unittest
from types import SimpleNamespace

from app.gestures.models import Gesture, Point3D
from app.gestures.stable_agent import (
    RecordingKeyboard,
    RecordingMouse,
    StableGestureAgent,
    StableGestureConfig,
)


class StableGestureV71SimplePalmTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mouse = RecordingMouse()
        self.keyboard = RecordingKeyboard()
        self.agent = StableGestureAgent(
            StableGestureConfig(
                dry_run=True,
                preview_enabled=False,
                pose_enter_frames=1,
                action_warmup_seconds=0.0,
                swipe_min_horizontal_ratio=0.11,
                swipe_max_vertical_ratio=0.40,
                swipe_max_duration_seconds=1.80,
                swipe_cooldown_seconds=0.70,
                simple_mode=False,
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

    def test_arming_immediately_prepares_open_palm_swipe(self) -> None:
        self.agent._set_armed(True, 1.0)
        self.assertTrue(self.agent._swipe_ready)

    def test_keep_palm_open_then_move_left_without_lowering_hand(self) -> None:
        self.agent._set_armed(True, 1.0)
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.20, 0.68)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.45, 0.55)
        )
        self.assertEqual(
            [name for name, _ in self.keyboard.calls].count("browser_back"),
            1,
        )

    def test_keep_palm_open_then_move_right_without_lowering_hand(self) -> None:
        self.agent._set_armed(True, 1.0)
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.20, 0.32)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.45, 0.45)
        )
        self.assertEqual(
            [name for name, _ in self.keyboard.calls].count("browser_forward"),
            1,
        )

    def test_open_palm_rearms_after_short_cooldown(self) -> None:
        self.agent._set_armed(True, 1.0)
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.10, 0.68)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 1.30, 0.55)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 2.05, 0.55)
        )
        self.agent.process_observation(
            self.observation(Gesture.OPEN_PALM, 2.25, 0.68)
        )
        names = [name for name, _ in self.keyboard.calls]
        self.assertEqual(names.count("browser_back"), 1)
        self.assertEqual(names.count("browser_forward"), 1)


if __name__ == "__main__":
    unittest.main()
