import unittest

from app.gestures.models import Gesture
from app.gestures.stable_agent import (
    PinchLatch,
    RecordingMouse,
    RobustGestureRecognizer,
    StableGestureAgent,
    StableGestureConfig,
)
from tests.unit.gesture_fixtures import make_hand_frame


class StableGestureV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.recognizer = RobustGestureRecognizer()

    def test_recognizes_open_palm(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, True, True, True))
        )
        self.assertEqual(observation.gesture, Gesture.OPEN_PALM)

    def test_recognizes_fist(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((False, False, False, False))
        )
        self.assertEqual(observation.gesture, Gesture.FIST)

    def test_recognizes_two_fingers(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, True, False, False))
        )
        self.assertEqual(observation.gesture, Gesture.TWO_FINGER)

    def test_recognizes_point(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, False, False, False))
        )
        self.assertEqual(observation.gesture, Gesture.POINT)

    def test_pinch_does_not_replace_point_pose(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, False, False, False), pinch="index")
        )
        self.assertEqual(observation.gesture, Gesture.POINT)
        self.assertLess(observation.metrics["index_pinch"], 0.44)

    def test_pinch_requires_two_frames_in_agent_configuration(self) -> None:
        config = StableGestureConfig(dry_run=True, preview_enabled=False)
        agent = StableGestureAgent(config)
        self.assertEqual(agent.pinch.enter_frames, 2)
        self.assertEqual(agent.pinch.release_frames, 2)

    def test_two_frame_pinch_clicks_once(self) -> None:
        pinch = PinchLatch(
            enter_ratio=0.44,
            release_ratio=0.62,
            cooldown_seconds=0.45,
            enter_frames=2,
            release_frames=2,
        )
        self.assertFalse(pinch.update(0.30, 1.0))
        self.assertTrue(pinch.update(0.30, 1.1))
        self.assertFalse(pinch.update(0.30, 1.2))
        self.assertFalse(pinch.update(0.70, 1.3))
        self.assertFalse(pinch.update(0.70, 1.4))
        self.assertFalse(pinch.update(0.30, 1.5))
        self.assertTrue(pinch.update(0.30, 1.6))

    def test_dry_run_uses_recording_mouse(self) -> None:
        agent = StableGestureAgent(
            StableGestureConfig(dry_run=True, preview_enabled=False)
        )
        self.assertIsInstance(agent.mouse, RecordingMouse)


if __name__ == "__main__":
    unittest.main()
