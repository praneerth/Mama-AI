import sys
import types
import unittest
from unittest.mock import patch

from app.gestures.config import GestureAgentConfig
from app.gestures.mediapipe_adapter import (
    GestureDependencyError,
    MediaPipeHandCamera,
)


class TestMediaPipeAdapterCompatibility(unittest.TestCase):
    def test_missing_legacy_solutions_api_fails_before_camera_open(self) -> None:
        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.VideoCapture = unittest.mock.Mock()
        fake_mediapipe = types.ModuleType("mediapipe")
        fake_mediapipe.__version__ = "0.10.31"

        with patch.dict(
            sys.modules,
            {"cv2": fake_cv2, "mediapipe": fake_mediapipe},
        ):
            with self.assertRaisesRegex(
                GestureDependencyError,
                r"mediapipe==0\.10\.21",
            ):
                MediaPipeHandCamera(GestureAgentConfig())

        fake_cv2.VideoCapture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
