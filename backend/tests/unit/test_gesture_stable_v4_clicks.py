import unittest

from app.gestures.stable_agent import (
    RecordingMouse,
    RobustGestureRecognizer,
    StableGestureAgent,
    StableGestureConfig,
)
from tests.unit.gesture_fixtures import make_hand_frame


class StableGestureV4ClickTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recognizer = RobustGestureRecognizer()
        self.mouse = RecordingMouse()
        self.agent = StableGestureAgent(
            StableGestureConfig(dry_run=True, preview_enabled=False),
            mouse=self.mouse,
        )
        self.agent.armed = True
        self.agent.armed_at = 0.0

    def _process_pinch(self, finger: str, started_at: float) -> None:
        for offset in (0.0, 0.05):
            frame = make_hand_frame(
                (True, False, False, False),
                timestamp=started_at + offset,
                pinch=finger,
            )
            self.agent.process_observation(self.recognizer.recognize(frame))

    def _release(self, timestamp: float) -> None:
        for offset in (0.0, 0.05):
            frame = make_hand_frame(
                (True, False, False, False),
                timestamp=timestamp + offset,
            )
            self.agent.process_observation(self.recognizer.recognize(frame))

    def test_recognizer_reports_all_three_pinch_metrics(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, False, False, False), pinch="middle")
        )
        self.assertIn("index_pinch", observation.metrics)
        self.assertIn("middle_pinch", observation.metrics)
        self.assertIn("ring_pinch", observation.metrics)
        self.assertLess(observation.metrics["middle_pinch"], 0.48)

    def test_index_pinch_generates_one_left_click(self) -> None:
        self._process_pinch("index", 1.0)
        self._release(1.2)
        self.assertEqual([name for name, _ in self.mouse.calls].count("left_click"), 1)
        self.assertNotIn("right_click", [name for name, _ in self.mouse.calls])
        self.assertNotIn("double_click", [name for name, _ in self.mouse.calls])

    def test_middle_pinch_generates_one_right_click(self) -> None:
        self._process_pinch("middle", 1.0)
        self.assertEqual([name for name, _ in self.mouse.calls].count("right_click"), 1)
        self.assertNotIn("left_click", [name for name, _ in self.mouse.calls])
        self.assertNotIn("double_click", [name for name, _ in self.mouse.calls])

    def test_ring_pinch_generates_one_double_click(self) -> None:
        self._process_pinch("ring", 1.0)
        self.assertEqual([name for name, _ in self.mouse.calls].count("double_click"), 1)
        self.assertNotIn("left_click", [name for name, _ in self.mouse.calls])
        self.assertNotIn("right_click", [name for name, _ in self.mouse.calls])

    def test_held_middle_pinch_does_not_repeat(self) -> None:
        self._process_pinch("middle", 1.0)
        self._process_pinch("middle", 1.1)
        self.assertEqual([name for name, _ in self.mouse.calls].count("right_click"), 1)

    def test_released_middle_pinch_can_click_again(self) -> None:
        self._process_pinch("middle", 1.0)
        self._release(1.2)
        self._process_pinch("middle", 1.8)
        self.assertEqual([name for name, _ in self.mouse.calls].count("right_click"), 2)

    def test_only_closest_finger_action_fires(self) -> None:
        self._process_pinch("ring", 1.0)
        action_names = [name for name, _ in self.mouse.calls]
        self.assertEqual(action_names.count("double_click"), 1)
        self.assertEqual(action_names.count("right_click"), 0)
        self.assertEqual(action_names.count("left_click"), 0)


if __name__ == "__main__":
    unittest.main()
