"""Command-line database migration, backup, verification, and restore tools."""

from __future__ import annotations

import argparse
import json
from typing import Any

from app.database.migrations import (
    MIGRATION_ROLLBACK_CONFIRMATION,
    migration_manager,
)
from app.database.recovery import RESTORE_CONFIRMATION, backup_manager


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mama-ai-database")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("migrate")
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--confirm", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--reason", default="manual_cli")
    listing = commands.add_parser("list")
    listing.add_argument("--limit", type=int, default=100)
    verify = commands.add_parser("verify")
    verify.add_argument("filename")
    prune = commands.add_parser("prune")
    prune.add_argument("--keep", type=int, default=None)
    integrity = commands.add_parser("integrity")
    integrity.add_argument("--full", action="store_true")
    restore = commands.add_parser("restore")
    restore.add_argument("filename")
    restore.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        _print({"migration": migration_manager.status(), "recovery": backup_manager.status()})
    elif args.command == "migrate":
        _print(migration_manager.migrate())
    elif args.command == "rollback":
        if args.confirm != MIGRATION_ROLLBACK_CONFIRMATION:
            raise SystemExit("Invalid rollback confirmation.")
        _print(migration_manager.rollback_last(confirmation=args.confirm))
    elif args.command == "backup":
        _print(backup_manager.create_backup(reason=args.reason))
    elif args.command == "list":
        _print({"backups": backup_manager.list_backups(limit=args.limit)})
    elif args.command == "verify":
        _print(backup_manager.verify_backup(args.filename))
    elif args.command == "prune":
        _print(backup_manager.prune_backups(keep=args.keep))
    elif args.command == "integrity":
        from app.database.recovery import run_integrity_check
        _print(run_integrity_check(backup_manager.database_path, mode="full" if args.full else "quick"))
    elif args.command == "restore":
        if args.confirm != RESTORE_CONFIRMATION:
            raise SystemExit("Invalid restore confirmation.")
        _print(backup_manager.restore_backup(args.filename, confirmation=args.confirm))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
