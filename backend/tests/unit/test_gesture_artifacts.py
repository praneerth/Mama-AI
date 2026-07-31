import json
import unittest
from pathlib import Path

from app.gestures.__main__ import build_parser
from app.gestures.profiles import ProfileRegistry


class TestGestureArtifacts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.backend_root = Path(__file__).resolve().parents[2]
        cls.repository_root = cls.backend_root.parent

    def test_native_dependencies_are_separate_from_production(self) -> None:
        gesture_requirements = (
            self.backend_root / "requirements-gesture.txt"
        ).read_text(encoding="utf-8").lower()
        production_requirements = (
            self.backend_root / "requirements-prod.txt"
        ).read_text(encoding="utf-8").lower()
        requirement_lines = {
            line.strip()
            for line in gesture_requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for dependency in (
            "numpy==1.26.4",
            "mediapipe==0.10.21",
            "opencv-contrib-python==4.11.0.86",
        ):
            self.assertIn(dependency, requirement_lines)
        self.assertTrue(
            any(line.startswith("pyautogui") for line in requirement_lines)
        )
        self.assertFalse(
            any(
                line.startswith("opencv-python")
                or line.startswith("opencv-python-headless")
                or line.startswith("opencv-contrib-python-headless")
                for line in requirement_lines
            )
        )
        for dependency in ("mediapipe", "opencv", "pyautogui"):
            self.assertNotIn(dependency, production_requirements)

    def test_ci_audits_gesture_dependencies(self) -> None:
        for workflow_name in ("backend-ci.yml", "backend-release.yml"):
            content = (
                self.repository_root
                / ".github"
                / "workflows"
                / workflow_name
            ).read_text(encoding="utf-8")
            self.assertIn("requirements-gesture.txt", content)

    def test_profiles_are_valid_json_and_load_strictly(self) -> None:
        directory = self.backend_root / "gesture_profiles"
        for path in directory.glob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))
        registry = ProfileRegistry.from_directory(directory)
        self.assertIn("default", registry.names())
        self.assertIn("offline_game", registry.names())

    def test_launcher_and_documentation_exist(self) -> None:
        self.assertTrue(
            (self.repository_root / "scripts" / "hand_gesture_agent.py").is_file()
        )
        self.assertTrue(
            (self.backend_root / "docs" / "hand_gestures.md").is_file()
        )

    def test_cli_parser_does_not_import_camera_dependencies(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--dry-run", "--profile", "default"])
        self.assertTrue(args.dry_run)
        self.assertEqual(args.profile, "default")

    def test_env_example_contains_safety_controls(self) -> None:
        content = (self.backend_root / ".env.example").read_text(
            encoding="utf-8"
        )
        self.assertIn("MAMA_GESTURE_ARM_HOLD_MS", content)
        self.assertIn("MAMA_GESTURE_STALE_FRAME_TIMEOUT_MS", content)
        self.assertIn("MAMA_GESTURE_DRY_RUN", content)
