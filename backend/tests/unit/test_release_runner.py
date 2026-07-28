import tempfile
import unittest
from pathlib import Path

from app.release.runner import (
    CommandResult,
    ReleaseCommandRunner,
    extract_unittest_count,
)


class TestReleaseRunner(unittest.TestCase):
    def test_extracts_last_unittest_count(self) -> None:
        output = "Ran 2 tests in 0.1s\nOK\nRan 504 tests in 40s\nOK"
        self.assertEqual(extract_unittest_count(output), 504)
        self.assertEqual(extract_unittest_count("no count"), 0)

    def test_compile_uses_backend_directory(self) -> None:
        calls = []

        def executor(command, cwd, timeout):
            calls.append((tuple(command), cwd, timeout))
            return CommandResult("command", tuple(command), 0, "", "")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend").mkdir()
            runner = ReleaseCommandRunner(
                root,
                executor=executor,
                python_executable="python-test",
            )
            result = runner.compile()

        self.assertTrue(result.passed)
        self.assertEqual(calls[0][1].name, "backend")
        self.assertEqual(calls[0][0][0], "python-test")
        self.assertIn("compileall", calls[0][0])

    def test_suite_returns_test_count(self) -> None:
        def executor(command, cwd, timeout):
            return CommandResult(
                "command",
                tuple(command),
                0,
                "",
                "Ran 118 tests in 3.0s\n\nOK",
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend").mkdir()
            runner = ReleaseCommandRunner(root, executor=executor)
            result, count = runner.run_suite("integration")

        self.assertTrue(result.passed)
        self.assertEqual(count, 118)
        self.assertIn("tests/integration", result.command)

    def test_unknown_suite_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend").mkdir()
            runner = ReleaseCommandRunner(root)
            with self.assertRaises(ValueError):
                runner.run_suite("performance")
