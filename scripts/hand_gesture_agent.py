"""Repository-root launcher for the Mama AI gesture agent."""

from __future__ import annotations

import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.gestures.__main__ import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
