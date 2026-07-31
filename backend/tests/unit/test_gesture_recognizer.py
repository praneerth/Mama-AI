import unittest

from app.gestures.models import Gesture
from app.gestures.recognizer import GestureRecognizer
from tests.unit.gesture_fixtures import make_hand_frame


class TestGestureRecognizer(unittest.TestCase):
    def setUp(self) -> None:
        self.recognizer = GestureRecognizer()

    def test_point(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, False, False, False))
        )
        self.assertEqual(observation.gesture, Gesture.POINT)

    def test_two_finger(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, True, False, False))
        )
        self.assertEqual(observation.gesture, Gesture.TWO_FINGER)

    def test_three_finger_arm_pose(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, True, True, False))
        )
        self.assertEqual(observation.gesture, Gesture.THREE_FINGER)

    def test_open_palm_and_fist(self) -> None:
        self.assertEqual(
            self.recognizer.recognize(
                make_hand_frame((True, True, True, True))
            ).gesture,
            Gesture.OPEN_PALM,
        )
        self.assertEqual(
            self.recognizer.recognize(
                make_hand_frame((False, False, False, False))
            ).gesture,
            Gesture.FIST,
        )

    def test_pinches_take_precedence(self) -> None:
        self.assertEqual(
            self.recognizer.recognize(
                make_hand_frame((True, False, False, False), pinch="index")
            ).gesture,
            Gesture.PINCH_INDEX,
        )
        self.assertEqual(
            self.recognizer.recognize(
                make_hand_frame((False, True, False, False), pinch="middle")
            ).gesture,
            Gesture.PINCH_MIDDLE,
        )
        self.assertEqual(
            self.recognizer.recognize(
                make_hand_frame((False, False, True, False), pinch="ring")
            ).gesture,
            Gesture.PINCH_RING,
        )

    def test_low_input_confidence_is_preserved(self) -> None:
        observation = self.recognizer.recognize(
            make_hand_frame((True, False, False, False), confidence=0.2)
        )
        self.assertLessEqual(observation.confidence, 0.2)
