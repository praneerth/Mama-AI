import unittest

from app.gestures.geometry import (
    CursorMapper,
    ExponentialPointSmoother,
    angle_degrees,
    distance_2d,
    extended_fingers,
    palm_scale,
)
from app.gestures.models import HandFrame, Point3D, points_from_sequence
from tests.unit.gesture_fixtures import make_hand_frame


class TestGestureModelsGeometry(unittest.TestCase):
    def test_hand_frame_requires_21_landmarks(self) -> None:
        with self.assertRaises(ValueError):
            HandFrame(landmarks=(Point3D(0, 0),), timestamp=0)

    def test_points_from_sequence_supports_two_and_three_values(self) -> None:
        points = points_from_sequence([(1, 2), (3, 4, 5)])
        self.assertEqual(points[0], Point3D(1.0, 2.0, 0.0))
        self.assertEqual(points[1], Point3D(3.0, 4.0, 5.0))

    def test_distance_and_straight_angle(self) -> None:
        self.assertAlmostEqual(distance_2d(Point3D(0, 0), Point3D(3, 4)), 5)
        self.assertAlmostEqual(
            angle_degrees(Point3D(0, 0), Point3D(1, 0), Point3D(2, 0)),
            180,
        )

    def test_extended_fingers_are_orientation_independent(self) -> None:
        frame = make_hand_frame((True, False, True, False))
        self.assertEqual(extended_fingers(frame), (True, False, True, False))
        self.assertGreater(palm_scale(frame), 0.1)

    def test_smoother_reduces_motion(self) -> None:
        smoother = ExponentialPointSmoother(alpha=0.5)
        self.assertEqual(smoother.update(Point3D(0, 0)), Point3D(0, 0))
        self.assertEqual(smoother.update(Point3D(1, 1)), Point3D(0.5, 0.5, 0.0))
        smoother.reset()
        self.assertEqual(smoother.update(Point3D(1, 1)), Point3D(1, 1))

    def test_cursor_mapper_mirrors_and_limits_large_jumps(self) -> None:
        mapper = CursorMapper(margin=0.0, mirror_x=True, maximum_step_pixels=100)
        first = mapper.map(Point3D(0.2, 0.5), 1000, 500)
        second = mapper.map(Point3D(1.0, 0.5), 1000, 500)
        self.assertGreater(first[0], 700)
        self.assertLessEqual(abs(second[0] - first[0]), 100)

    def test_invalid_geometry_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ExponentialPointSmoother(alpha=0)
        with self.assertRaises(ValueError):
            CursorMapper(margin=0.5)
