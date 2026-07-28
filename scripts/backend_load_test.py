"""Run the Mama AI bounded release load test from the repository root."""

from __future__ import annotations

from pathlib import Path
import os
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.release.__main__ import main  # noqa: E402


if __name__ == "__main__":
    # The bearer token can be supplied through the environment without being
    # displayed in shell history. The CLI never writes it into the report.
    if "--bearer-token" not in sys.argv and os.getenv("MAMA_RELEASE_BEARER_TOKEN"):
        sys.argv.extend([
            "--bearer-token",
            os.environ["MAMA_RELEASE_BEARER_TOKEN"],
        ])
    if len(sys.argv) == 1 or sys.argv[1] != "load":
        sys.argv.insert(1, "load")
    raise SystemExit(main())
