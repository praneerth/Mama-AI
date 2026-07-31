from pathlib import Path
import unittest


class StableGestureArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = Path(__file__).resolve().parents[2]
        self.root = self.backend.parent

    def test_root_launchers_exist(self) -> None:
        for name in (
            "SETUP_HAND_GESTURES.cmd",
            "TEST_HAND_GESTURES.cmd",
            "START_HAND_GESTURES.cmd",
            "START_HAND_GESTURES_FAST.cmd",
            "STOP_HAND_GESTURES.cmd",
        ):
            self.assertTrue((self.root / name).is_file(), name)

    def test_stable_launcher_exists(self) -> None:
        self.assertTrue((self.root / "scripts" / "hand_gesture_stable.py").is_file())

    def test_requirements_pin_compatible_cv_stack(self) -> None:
        text = (self.backend / "requirements-gesture.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("numpy==1.26.4", text)
        self.assertIn("mediapipe==0.10.21", text)
        self.assertIn("opencv-contrib-python==4.11.0.86", text)
        self.assertNotIn("opencv-python-headless", text)

    def test_stable_agent_does_not_import_backend_settings(self) -> None:
        text = (
            self.backend / "app" / "gestures" / "stable_agent.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("app.config.settings", text)
        self.assertNotIn("dotenv", text)
        self.assertIn("LatestFrameCapture", text)
        self.assertIn("NativeWindowsMouse", text)


if __name__ == "__main__":
    unittest.main()
