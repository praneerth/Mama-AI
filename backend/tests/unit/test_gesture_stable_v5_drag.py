import unittest

from app.gestures.stable_agent import (
    RecordingMouse,
    RobustGestureRecognizer,
    StableGestureAgent,
    StableGestureConfig,
)
from tests.unit.gesture_fixtures import make_hand_frame


class StableGestureV5DragTests(unittest.TestCase):
    def setUp(self) -> None:
        self.recognizer = RobustGestureRecognizer()
        self.mouse = RecordingMouse()
        self.agent = StableGestureAgent(
            StableGestureConfig(
                dry_run=True,
                preview_enabled=False,
                drag_hold_seconds=0.50,
            ),
            mouse=self.mouse,
        )
        self.agent.armed = True
        self.agent.armed_at = 0.0

    def process(self, timestamp: float, pinch: str | None = None) -> None:
        frame = make_hand_frame(
            (True, False, False, False),
            timestamp=timestamp,
            pinch=pinch,
        )
        self.agent.process_observation(self.recognizer.recognize(frame))

    def release_index(self, timestamp: float) -> None:
        self.process(timestamp)
        self.process(timestamp + 0.05)

    def test_quick_index_pinch_clicks_on_release(self) -> None:
        self.process(1.00, "index")
        self.process(1.05, "index")
        self.release_index(1.20)
        names = [name for name, _ in self.mouse.calls]
        self.assertEqual(names.count("left_click"), 1)
        self.assertNotIn("left_down", names)

    def test_held_index_pinch_starts_drag_and_release_drops(self) -> None:
        self.process(1.00, "index")
        self.process(1.05, "index")
        self.process(1.60, "index")
        names = [name for name, _ in self.mouse.calls]
        self.assertEqual(names.count("left_down"), 1)
        self.release_index(1.70)
        names = [name for name, _ in self.mouse.calls]
        self.assertEqual(names.count("left_up"), 1)
        self.assertNotIn("left_click", names)

    def test_no_hand_releases_active_drag(self) -> None:
        self.process(1.00, "index")
        self.process(1.05, "index")
        self.process(1.60, "index")
        self.agent.process_no_hand(1.70)
        names = [name for name, _ in self.mouse.calls]
        self.assertEqual(names.count("left_up"), 1)


if __name__ == "__main__":
    unittest.main()
