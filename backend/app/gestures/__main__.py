"""Run the Mama AI native hand-gesture agent."""

from __future__ import annotations

import argparse
import logging
from dataclasses import replace
from pathlib import Path

from app.gestures.config import GestureAgentConfig
from app.gestures.service import GestureAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mama AI Windows hand-gesture agent"
    )
    parser.add_argument("--camera", type=int, help="Camera index")
    parser.add_argument("--profile", help="Default gesture profile")
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        help="Directory containing gesture profile JSON files",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="Disable the local camera preview",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Recognize gestures without controlling the desktop",
    )
    parser.add_argument(
        "--no-auto-profile",
        action="store_true",
        help="Disable foreground-window profile selection",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    config = GestureAgentConfig.from_environment()
    overrides: dict[str, object] = {}
    if args.camera is not None:
        overrides["camera_index"] = args.camera
    if args.profile:
        overrides["profile_name"] = args.profile
    if args.profiles_dir:
        overrides["profiles_directory"] = args.profiles_dir.resolve()
    if args.no_preview:
        overrides["preview_enabled"] = False
    if args.dry_run:
        overrides["dry_run"] = True
    if args.no_auto_profile:
        overrides["auto_select_profiles"] = False
    config = replace(config, **overrides)
    summary = GestureAgent(config).run()
    print(
        "Mama AI gesture agent stopped: "
        f"frames={summary.frames}, valid={summary.valid_hand_frames}, "
        f"actions={summary.dispatched_actions}, reason={summary.exit_reason}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
