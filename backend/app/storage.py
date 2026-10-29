"""Keeps everything the app writes (the data directory) under a size cap.

Hosts like Railway sell disk in small tiers, so the cap matters more than the age-based
retention settings: when the data directory grows past it, the oldest scan images go first,
then the oldest alerts, until usage is back under PRUNE_TO of the limit.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path

from sqlalchemy import select

from . import db, settings_store

log = logging.getLogger(__name__)

MB = 1024 * 1024
# Prune a little below the limit so we don't run again on the very next frame.
PRUNE_TO = 0.9
# Leave this much of the real disk free even when the configured limit is larger than the disk.
DISK_RESERVE = 20 * MB
RESCAN_SEC = 300

_lock = threading.Lock()
_enforce_lock = threading.Lock()
_used: int | None = None
_scanned_at = 0.0


def dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def usage() -> dict:
    """Full breakdown of the data directory, in bytes."""
    data = db.DATA_DIR
    snapshots = dir_size(db.SNAPSHOT_DIR)
    database = sum(p.stat().st_size for p in data.glob(f"{db.DB_NAME}*") if p.is_file())
    total = dir_size(data)
    limit = limit_bytes()
    disk = shutil.disk_usage(data)
    return {
        "used": total, "limit": limit, "effective_limit": effective_limit(total, limit),
        "snapshots": snapshots, "database": database, "other": max(0, total - snapshots - database),
        "disk_free": disk.free,
    }


def limit_bytes() -> int:
    return int(settings_store.get("storage_limit_mb")) * MB


def effective_limit(used: int, limit: int) -> int:
    """The configured limit, or less if the disk itself would fill up first."""
    free = shutil.disk_usage(db.DATA_DIR).free
    return max(0, min(limit, used + free - DISK_RESERVE))


def note_written(nbytes: int) -> None:
    """Called after each new file so enforce() can skip the directory walk most of the time."""
    global _used
    with _lock:
        if _used is not None:
            _used += nbytes


def _current(force: bool) -> int:
    global _used, _scanned_at
    with _lock:
        if force or _used is None or time.monotonic() - _scanned_at > RESCAN_SEC:
            _used, _scanned_at = dir_size(db.DATA_DIR), time.monotonic()
        return _used


def enforce(force: bool = False) -> dict:
    """Delete the oldest data until the data directory fits. Returns what was removed."""
    # Two detector threads can finish frames at once; one prune at a time is enough.
    if not _enforce_lock.acquire(blocking=force):
        return {"snapshots_deleted": 0, "events_deleted": 0, "freed_mb": 0.0}
    try:
        return _enforce(force)
    finally:
        _enforce_lock.release()


def _enforce(force: bool) -> dict:
    used = _current(force)
    limit = effective_limit(used, limit_bytes())
    if used <= limit:
        return {"snapshots_deleted": 0, "events_deleted": 0, "freed_mb": 0.0}
    target = int(limit * PRUNE_TO)
    start = used
    snaps = events = 0
    while used > target:
        n, freed = _prune_snapshots(used - target)
        snaps += n
        used -= freed
        if used <= target:
            break
        # Every remaining image belongs to an alert or is a camera's latest frame: drop the oldest alerts.
        pruned = _prune_events(50)
        if not pruned:
            break
        events += pruned
    _compact()
    used = _current(True)
    if used > limit:
        log.warning("data directory is %.0f MB, still over the %.0f MB storage limit", used / MB, limit / MB)
    result = {"snapshots_deleted": snaps, "events_deleted": events, "freed_mb": round((start - used) / MB, 1)}
    log.info("storage limit: %s", result)
    return result


def _prune_snapshots(need: int) -> tuple[int, int]:
    """Delete the oldest unreferenced snapshots until `need` bytes of images are gone."""
    freed = 0
    ids: list[int] = []
    with db.session() as s:
        keep = set()
        for a, b in s.query(db.Event.snapshot_id, db.Event.prev_snapshot_id):
            keep.update(x for x in (a, b) if x)
        keep.update(x for (x,) in s.query(db.Camera.last_snapshot_id) if x)
        for snap_id, path in s.execute(select(db.Snapshot.id, db.Snapshot.path).order_by(db.Snapshot.ts)):
            if freed >= need:
                break
            if snap_id in keep:
                continue
            p = Path(path)
            try:
                freed += p.stat().st_size
                p.unlink()
            except OSError:
                pass
            ids.append(snap_id)
        for i in range(0, len(ids), 500):
            s.query(db.Snapshot).filter(db.Snapshot.id.in_(ids[i:i + 500])).delete(synchronize_session=False)
        s.commit()
    return len(ids), freed


def _prune_events(n: int) -> int:
    with db.session() as s:
        ids = list(s.scalars(select(db.Event.id).order_by(db.Event.ts).limit(n)))
        if ids:
            s.query(db.Event).filter(db.Event.id.in_(ids)).delete(synchronize_session=False)
            s.commit()
    return len(ids)


def _compact() -> None:
    """Hand freed database pages back to the filesystem."""
    with db.engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.exec_driver_sql("PRAGMA incremental_vacuum")
        conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
