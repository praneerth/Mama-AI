import unittest

from app.gestures.models import Gesture, Point3D
from app.gestures.stable_agent import (
    HoldDetector,
    PinchLatch,
    PoseDebouncer,
    RecordingMouse,
    RelativePointerController,
    ScrollController,
    StableGestureAgent,
    StableGestureConfig,
)


class StableGestureUnitTests(unittest.TestCase):
    def test_pose_debouncer_rejects_single_frame_flicker(self) -> None:
        debounce = PoseDebouncer(enter_frames=2, release_frames=3)
        self.assertEqual(debounce.update(Gesture.POINT), Gesture.NONE)
        self.assertEqual(debounce.update(Gesture.POINT), Gesture.POINT)
        self.assertEqual(debounce.update(Gesture.TWO_FINGER), Gesture.POINT)
        self.assertEqual(debounce.update(Gesture.POINT), Gesture.POINT)

    def test_hold_detector_fires_once(self) -> None:
        hold = HoldDetector(0.5)
        self.assertFalse(hold.update(Gesture.OPEN_PALM, Gesture.OPEN_PALM, 1.0))
        self.assertFalse(hold.update(Gesture.OPEN_PALM, Gesture.OPEN_PALM, 1.4))
        self.assertTrue(hold.update(Gesture.OPEN_PALM, Gesture.OPEN_PALM, 1.5))
        self.assertFalse(hold.update(Gesture.OPEN_PALM, Gesture.OPEN_PALM, 2.0))

    def test_pinch_hysteresis_clicks_once_until_release(self) -> None:
        pinch = PinchLatch(0.30, 0.46, 0.4)
        self.assertTrue(pinch.update(0.25, 1.0))
        self.assertFalse(pinch.update(0.24, 1.1))
        self.assertFalse(pinch.update(0.40, 1.2))
        self.assertFalse(pinch.update(0.50, 1.3))
        self.assertFalse(pinch.update(0.25, 1.35))
        self.assertFalse(pinch.update(0.50, 1.5))
        self.assertTrue(pinch.update(0.25, 1.8))

    def test_relative_pointer_starts_at_current_cursor_without_jump(self) -> None:
        pointer = RelativePointerController()
        start = pointer.update(Point3D(0.5, 0.5), (800, 450), (1600, 900))
        self.assertEqual(start, (800, 450))
        moved = pointer.update(Point3D(0.55, 0.5), (800, 450), (1600, 900))
        self.assertGreater(moved[0], 800)
        self.assertLess(moved[0], 1600)

    def test_relative_pointer_clamps_inside_screen(self) -> None:
        pointer = RelativePointerController(maximum_step_pixels=1000)
        pointer.update(Point3D(0.5, 0.5), (500, 300), (1000, 600))
        result = pointer.update(Point3D(3.0, -3.0), (500, 300), (1000, 600))
        self.assertGreaterEqual(result[0], 3)
        self.assertLessEqual(result[0], 996)
        self.assertGreaterEqual(result[1], 3)
        self.assertLessEqual(result[1], 596)

    def test_scroll_accumulates_small_movements(self) -> None:
        scroll = ScrollController(dead_zone=0.001, scale=50.0, maximum_notches=2)
        self.assertEqual(scroll.update(0.5), 0)
        amount = scroll.update(0.45)
        self.assertGreater(amount, 0)

    def test_config_rejects_bad_pinch_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            StableGestureConfig(pinch_enter_ratio=0.5, pinch_release_ratio=0.4)

    def test_dry_run_uses_recording_mouse(self) -> None:
        agent = StableGestureAgent(
            StableGestureConfig(dry_run=True, preview_enabled=False)
        )
        self.assertIsInstance(agent.mouse, RecordingMouse)


if __name__ == "__main__":
    unittest.main()
