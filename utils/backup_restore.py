"""
utils/backup_restore.py

Database backup and restore via mysqldump/mysql CLI tools (shelling
out, rather than reimplementing MySQL's dump format). This is the
module ui/pages/settings_page.py already has a graceful ImportError
fallback for - implementing it here makes that page's "Create Backup
Now" button actually work.

Requires the `mysqldump` and `mysql` command-line client tools to be
installed and on PATH (they ship with any standard MySQL/MariaDB
client installation - separate from the mysql-connector-python
Python package used elsewhere in this app for querying).

Usage:
    from utils.backup_restore import create_backup, restore_backup, list_backups

    filepath = create_backup()                    # automatic filename + timestamp
    filepath = create_backup(note="pre-migration")  # custom label in filename

    restore_backup(filepath)                       # DESTRUCTIVE - see docstring

    backups = list_backups()                       # from the `backups` table
"""

import logging
import subprocess
from datetime import datetime
from pathlib import Path

import config
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.utils.backup_restore")


class BackupError(Exception):
    """Raised when a backup or restore operation fails."""
    pass


def _check_tool_available(tool_name: str) -> bool:
    try:
        subprocess.run([tool_name, "--version"], capture_output=True, timeout=5, check=False)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def create_backup(note: str = None, backup_type: str = "Manual") -> str:
    """
    Dumps the full database to a timestamped .sql file under
    data/backups/, records the backup in the `backups` table, and
    returns the filepath.

    Raises BackupError if mysqldump isn't available or the dump fails.
    """
    if not _check_tool_available("mysqldump"):
        raise BackupError(
            "mysqldump command not found on PATH. Install the MySQL client tools "
            "(separate from the mysql-connector-python package) to enable backups."
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{note}" if note else ""
    filename = f"backup_{timestamp}{suffix}.sql"
    filepath = config.BACKUPS_DIR / filename
    config.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

    command = [
        "mysqldump",
        f"--host={config.DB_CONFIG['host']}",
        f"--port={config.DB_CONFIG['port']}",
        f"--user={config.DB_CONFIG['user']}",
        f"--password={config.DB_CONFIG['password']}",
        "--single-transaction",   # consistent snapshot without locking tables
        "--routines",
        "--triggers",
        config.DB_CONFIG["database"],
    ]

    try:
        with open(filepath, "w", encoding="utf-8") as out_file:
            result = subprocess.run(
                command, stdout=out_file, stderr=subprocess.PIPE, timeout=300, check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise BackupError("Backup timed out after 5 minutes.") from exc

    if result.returncode != 0:
        error_output = result.stderr.decode("utf-8", errors="replace")
        filepath.unlink(missing_ok=True)
        raise BackupError(f"mysqldump failed: {error_output}")

    size_mb = filepath.stat().st_size / (1024 * 1024)

    try:
        db.execute(
            "INSERT INTO backups (backup_path, backup_type, backup_size_mb) VALUES (%s, %s, %s)",
            (str(filepath), backup_type, round(size_mb, 2)),
        )
    except Exception as exc:
        logger.warning("Backup file created but failed to record in `backups` table: %s", exc)

    logger.info("Backup created: %s (%.2f MB).", filepath, size_mb)
    return str(filepath)


def restore_backup(filepath: str) -> bool:
    """
    Restores the database from a .sql dump file, OVERWRITING current
    data. This is destructive and irreversible without a prior backup
    of the current state - callers (e.g. the Settings page) should
    confirm with the user before calling this, and ideally call
    create_backup() first as a safety net.
    """
    if not _check_tool_available("mysql"):
        raise BackupError(
            "mysql command not found on PATH. Install the MySQL client tools to enable restore."
        )

    filepath = Path(filepath)
    if not filepath.exists():
        raise BackupError(f"Backup file not found: {filepath}")

    command = [
        "mysql",
        f"--host={config.DB_CONFIG['host']}",
        f"--port={config.DB_CONFIG['port']}",
        f"--user={config.DB_CONFIG['user']}",
        f"--password={config.DB_CONFIG['password']}",
        config.DB_CONFIG["database"],
    ]

    try:
        with open(filepath, "r", encoding="utf-8") as in_file:
            result = subprocess.run(
                command, stdin=in_file, stderr=subprocess.PIPE, timeout=300, check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise BackupError("Restore timed out after 5 minutes.") from exc

    if result.returncode != 0:
        error_output = result.stderr.decode("utf-8", errors="replace")
        raise BackupError(f"Restore failed: {error_output}")

    logger.warning("Database restored from backup: %s. Existing data was overwritten.", filepath)
    return True


def list_backups(limit: int = 50) -> list:
    """Returns backup records from the `backups` table, most recent first."""
    try:
        return db.fetch_all(
            "SELECT * FROM backups ORDER BY created_at DESC LIMIT %s", (limit,)
        )
    except Exception as exc:
        logger.error("Failed to list backups: %s", exc)
        return []


def delete_backup_file(filepath: str, remove_record: bool = True) -> bool:
    """Deletes a backup file from disk, and optionally its `backups` table record."""
    path = Path(filepath)
    try:
        if path.exists():
            path.unlink()
        if remove_record:
            db.execute("DELETE FROM backups WHERE backup_path = %s", (str(filepath),))
        logger.info("Backup deleted: %s", filepath)
        return True
    except Exception as exc:
        logger.error("Failed to delete backup %s: %s", filepath, exc)
        return False