"""Shared database helpers."""

import sqlite3
from pathlib import Path

from settings import DB_PATH, ROOT  # noqa: F401  (ROOT re-exported for older imports)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def read_only_uri(path):
    """SQLite URI that opens `path` read-only. as_uri() percent-encodes the path,
    so spaces, '?' or '#' in a folder name can't break it."""
    return Path(path).resolve().as_uri() + "?mode=ro"


def connect(path=None, read_only=False):
    """Open a SQLite connection.

    read_only=True is for serving: the Yelp data never changes while the app
    runs, and a read-only connection can't change it by accident.
    A connection belongs to one thread; servers should open one per thread.
    """
    path = path or DB_PATH
    if read_only:
        con = sqlite3.connect(read_only_uri(path), uri=True)
    else:
        con = sqlite3.connect(path)
        # No journal file on disk: the database can always be rebuilt from the JSON files.
        con.execute("PRAGMA journal_mode=MEMORY")
        con.execute("PRAGMA synchronous=OFF")
    con.row_factory = sqlite3.Row
    return con
