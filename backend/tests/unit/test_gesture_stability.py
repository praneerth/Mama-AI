import unittest

from app.gestures.models import Gesture, Point3D
from app.gestures.stability import (
    CooldownRegistry,
    GestureLatch,
    ScrollTracker,
    SwipeDetector,
)


class TestGestureStability(unittest.TestCase):
    def test_latch_requires_dwell_and_one_release(self) -> None:
        latch = GestureLatch()
        self.assertFalse(latch.update(Gesture.FIST, 1.0, 100))
        self.assertFalse(latch.update(Gesture.FIST, 1.05, 100))
        self.assertTrue(latch.update(Gesture.FIST, 1.11, 100))
        self.assertFalse(latch.update(Gesture.FIST, 1.30, 100))
        latch.update(Gesture.NONE, 1.31, 0)
        self.assertFalse(latch.update(Gesture.FIST, 1.32, 100))

    def test_cooldown(self) -> None:
        cooldown = CooldownRegistry()
        self.assertTrue(cooldown.ready("click", 1.0, 500))
        cooldown.mark("click", 1.0)
        self.assertFalse(cooldown.ready("click", 1.2, 500))
        self.assertTrue(cooldown.ready("click", 1.6, 500))

    def test_scroll_tracker_has_dead_zone(self) -> None:
        tracker = ScrollTracker(dead_zone=0.02, scale=1000)
        self.assertEqual(tracker.update(0.5), 0)
        self.assertEqual(tracker.update(0.49), 0)
        self.assertGreater(tracker.update(0.44), 0)
        tracker.reset()
        self.assertEqual(tracker.update(0.3), 0)

    def test_swipe_directions_and_latch(self) -> None:
        detector = SwipeDetector(
            window_ms=500,
            minimum_distance=0.2,
            maximum_cross_axis=0.1,
        )
        self.assertEqual(detector.update(Point3D(0.2, 0.5), 0.0, True), Gesture.NONE)
        self.assertEqual(
            detector.update(Point3D(0.45, 0.52), 0.2, True),
            Gesture.SWIPE_RIGHT,
        )
        self.assertEqual(detector.update(Point3D(0.7, 0.5), 0.3, True), Gesture.NONE)
        detector.update(Point3D(0.7, 0.5), 0.4, False)
        self.assertEqual(detector.update(Point3D(0.7, 0.7), 1.0, True), Gesture.NONE)
        self.assertEqual(
            detector.update(Point3D(0.69, 0.4), 1.2, True),
            Gesture.SWIPE_UP,
        )

    def test_cross_axis_motion_is_not_a_swipe(self) -> None:
        detector = SwipeDetector(minimum_distance=0.2, maximum_cross_axis=0.05)
        detector.update(Point3D(0.2, 0.2), 0.0, True)
        self.assertEqual(
            detector.update(Point3D(0.5, 0.5), 0.2, True),
            Gesture.NONE,
        )


class TestGestureStabilizer(unittest.TestCase):
    def test_single_frame_flicker_does_not_change_stable_pose(self) -> None:
        from app.gestures.stability import GestureStabilizer

        stabilizer = GestureStabilizer(enter_frames=3, release_frames=2)
        self.assertEqual(stabilizer.update(Gesture.POINT), Gesture.NONE)
        self.assertEqual(stabilizer.update(Gesture.POINT), Gesture.NONE)
        self.assertEqual(stabilizer.update(Gesture.POINT), Gesture.POINT)
        self.assertEqual(stabilizer.update(Gesture.TWO_FINGER), Gesture.POINT)
        self.assertEqual(stabilizer.update(Gesture.POINT), Gesture.POINT)

    def test_pose_changes_only_after_required_matching_frames(self) -> None:
        from app.gestures.stability import GestureStabilizer

        stabilizer = GestureStabilizer(enter_frames=2, release_frames=2)
        self.assertEqual(stabilizer.update(Gesture.POINT), Gesture.NONE)
        self.assertEqual(stabilizer.update(Gesture.POINT), Gesture.POINT)
        self.assertEqual(stabilizer.update(Gesture.TWO_FINGER), Gesture.POINT)
        self.assertEqual(
            stabilizer.update(Gesture.TWO_FINGER), Gesture.TWO_FINGER
        )
        self.assertEqual(stabilizer.update(Gesture.NONE), Gesture.TWO_FINGER)
        self.assertEqual(stabilizer.update(Gesture.NONE), Gesture.NONE)
