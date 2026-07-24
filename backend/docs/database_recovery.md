# Mama AI Database Recovery Runbook

Mama AI uses SQLite's online backup API, versioned migration checksums, and
verified sidecar metadata. Backups are stored outside the runtime database
folder by default.

## Routine commands

Run from `backend` with the virtual environment active:

```cmd
python -m app.database.recovery_cli status
python -m app.database.recovery_cli migrate
python -m app.database.recovery_cli backup --reason manual_before_upgrade
python -m app.database.recovery_cli list
python -m app.database.recovery_cli verify BACKUP_FILENAME.db
python -m app.database.recovery_cli prune --keep 14
python -m app.database.recovery_cli integrity --full
```

## Restore procedure

1. Stop the Mama AI API and every worker that can access SQLite.
2. Verify the selected backup.
3. Restore with the explicit confirmation phrase.
4. Start Mama AI and check `/health/ready` plus `/admin/database/status`.

```cmd
python -m app.database.recovery_cli verify BACKUP_FILENAME.db
python -m app.database.recovery_cli restore BACKUP_FILENAME.db --confirm RESTORE_MAMA_AI_DATABASE
```

A pre-restore safety backup is created automatically when a runtime database
already exists. A failed replacement attempts to restore the prior database.
Never edit a backup file or its `.db.json` sidecar.

## Migration rollback

Only migrations explicitly marked reversible can be rolled back. Stop the API
before rollback and create a backup first.

```cmd
python -m app.database.recovery_cli rollback --confirm ROLLBACK_LAST_MAMA_AI_MIGRATION
```

Historical migration files must never be edited after release. Checksum drift
causes startup migration to fail closed.
