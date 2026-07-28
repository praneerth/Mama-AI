"""Command execution helpers for local and CI release validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
import re
import subprocess
import sys


_TEST_COUNT = re.compile(r"Ran\s+(\d+)\s+tests?", re.IGNORECASE)


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.return_code == 0

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part)


Executor = Callable[[Sequence[str], Path, int], CommandResult]


def execute_command(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
    *,
    name: str = "command",
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        return CommandResult(
            name=name,
            command=tuple(str(item) for item in command),
            return_code=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            name=name,
            command=tuple(str(item) for item in command),
            return_code=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr="Command timed out.",
        )


def extract_unittest_count(output: str) -> int:
    matches = _TEST_COUNT.findall(output)
    if not matches:
        return 0
    return int(matches[-1])


class ReleaseCommandRunner:
    """Run compile and unittest gates without storing secrets in reports."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        executor: Executor | None = None,
        python_executable: str | None = None,
    ) -> None:
        self.repository_root = Path(repository_root).resolve()
        self.backend_root = self.repository_root / "backend"
        self.executor = executor or self._execute
        self.python_executable = python_executable or sys.executable

    def _execute(
        self,
        command: Sequence[str],
        cwd: Path,
        timeout_seconds: int,
    ) -> CommandResult:
        return execute_command(
            command,
            cwd,
            timeout_seconds,
            name=" ".join(command),
        )

    def _run(
        self,
        name: str,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: int = 1800,
    ) -> CommandResult:
        result = self.executor(
            tuple(command),
            cwd or self.backend_root,
            timeout_seconds,
        )
        if result.name == "command":
            return CommandResult(
                name=name,
                command=result.command,
                return_code=result.return_code,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result

    def compile(self) -> CommandResult:
        return self._run(
            "python.compile",
            (
                self.python_executable,
                "-m",
                "compileall",
                "-q",
                "app",
                "tests",
                "main.py",
            ),
        )

    def run_suite(self, suite: str) -> tuple[CommandResult, int]:
        if suite not in {"unit", "integration", "smoke"}:
            raise ValueError("Suite must be unit, integration, or smoke.")
        result = self._run(
            f"tests.{suite}",
            (
                self.python_executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                f"tests/{suite}",
                "-p",
                "test_*.py",
            ),
        )
        return result, extract_unittest_count(result.combined_output)

    def git_value(self, *arguments: str) -> CommandResult:
        return self._run(
            "git." + ".".join(arguments),
            ("git", *arguments),
            cwd=self.repository_root,
            timeout_seconds=60,
        )
