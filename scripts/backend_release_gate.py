"""Create a final Mama AI release report from explicit evidence JSON."""

from __future__ import annotations

from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.release.__main__ import main  # noqa: E402


if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1] != "evaluate":
        sys.argv.insert(1, "evaluate")
    raise SystemExit(main())
