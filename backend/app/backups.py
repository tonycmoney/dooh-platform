"""Daily database backups with pg_dump.

A background thread checks every half hour and makes a backup when the newest
one is more than a day old, so a restart or a deploy never skips a day. Dumps
are pg_dump's custom format (restore with pg_restore) and are kept for
BACKUP_KEEP_DAYS. They can be listed and downloaded from the dashboard.
"""

import logging
import re
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings

log = logging.getLogger("dooh.backups")

BACKUP_NAME = re.compile(r"^dooh-\d{8}-\d{6}\.dump$")
CHECK_EVERY_SECONDS = 30 * 60
BACKUP_EVERY = timedelta(days=1)
MIN_KEPT = 3  # never prune below this many, even if they are old
DUMP_TIMEOUT = 30 * 60

_lock = threading.Lock()


@dataclass
class Backup:
    name: str
    size_bytes: int
    created_at: datetime


def backup_dir() -> Path:
    return settings.resolved_backup_dir()


def list_backups() -> list[Backup]:
    """Newest first."""
    backups = []
    for path in backup_dir().iterdir():
        if path.is_file() and BACKUP_NAME.match(path.name):
            stat = path.stat()
            backups.append(Backup(path.name, stat.st_size, datetime.fromtimestamp(stat.st_mtime, timezone.utc)))
    return sorted(backups, key=lambda b: b.created_at, reverse=True)


def backup_path(name: str) -> Path | None:
    """The backup's path, or None for anything that isn't one of ours."""
    if not BACKUP_NAME.match(name):
        return None
    path = backup_dir() / name
    return path if path.is_file() else None


def run_backup() -> Backup:
    """Dumps the database now. Raises RuntimeError if pg_dump fails."""
    with _lock:
        name = datetime.now(timezone.utc).strftime("dooh-%Y%m%d-%H%M%S.dump")
        target = backup_dir() / name
        partial = target.with_suffix(".partial")
        try:
            result = subprocess.run(
                ["pg_dump", "--format=custom", "--no-owner", "--no-acl",
                 "--file", str(partial), "--dbname", settings.libpq_database_url],
                capture_output=True, text=True, timeout=DUMP_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"pg_dump could not run: {e}") from e
        if result.returncode != 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"pg_dump failed: {result.stderr.strip()[-500:]}")
        partial.rename(target)
        _prune()
        log.info("Database backup written: %s (%d bytes)", name, target.stat().st_size)
        return next(b for b in list_backups() if b.name == name)


def _prune() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.backup_keep_days)
    for backup in list_backups()[MIN_KEPT:]:
        if backup.created_at < cutoff:
            (backup_dir() / backup.name).unlink(missing_ok=True)


def backup_due() -> bool:
    backups = list_backups()
    return not backups or datetime.now(timezone.utc) - backups[0].created_at >= BACKUP_EVERY


def _scheduler(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            if backup_due():
                run_backup()
        except Exception:
            log.exception("Scheduled database backup failed; retrying in %d min", CHECK_EVERY_SECONDS // 60)
        stop.wait(CHECK_EVERY_SECONDS)


def start_scheduler() -> threading.Event:
    """Starts the daily backup thread. Set the returned event to stop it."""
    stop = threading.Event()
    threading.Thread(target=_scheduler, args=(stop,), name="daily-backups", daemon=True).start()
    return stop
