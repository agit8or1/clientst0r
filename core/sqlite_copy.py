"""Copying a live SQLite database safely.

The database runs in WAL mode (config/settings.py): a commit is written to
db.sqlite3-wal first and reaches db.sqlite3 only at the next checkpoint. A
file copy of db.sqlite3 (cp, shutil.copy) therefore misses recent commits,
and copying a file over the live database leaves the old -wal and -shm
beside it, which SQLite would replay onto the new file. Every backup and
restore goes through SQLite's online backup API instead: it reads the
database the way a connection does (WAL contents included, one consistent
snapshot, other connections keep working) and writes the destination
through SQLite as well.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def copy_database(src_path, dst_path, *, timeout: float = 60) -> Path:
    """An online, consistent copy of the database at `src_path`, written to
    `dst_path` as one self-contained file (rollback journal, no -wal/-shm),
    so it can be hashed, archived or copied like any file."""
    src = sqlite3.connect(f'file:{src_path}?mode=ro', uri=True, timeout=timeout)
    try:
        dst = sqlite3.connect(str(dst_path), timeout=timeout)
        try:
            src.backup(dst)
            # The copy inherits the source's WAL flag; a standalone file
            # must not depend on a -wal beside it.
            dst.execute('PRAGMA journal_mode=DELETE')
        finally:
            dst.close()
    finally:
        src.close()
    return Path(dst_path)


def restore_database(src_path, live_path, *, timeout: float = 60) -> None:
    """Replace the contents of the database at `live_path` with the copy at
    `src_path`, page by page through SQLite (the live file keeps its journal
    mode; its -wal and -shm stay consistent; open connections see the new
    contents on their next transaction)."""
    src = sqlite3.connect(f'file:{src_path}?mode=ro', uri=True, timeout=timeout)
    try:
        dst = sqlite3.connect(str(live_path), timeout=timeout)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
