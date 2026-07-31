"""Repository-root launcher for Mama AI stable hand gestures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.gestures.stable_agent import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
