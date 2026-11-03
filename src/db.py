"""Shared database helpers."""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "yelp.db"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def connect(path=DB_PATH):
    con = sqlite3.connect(path)
    # No journal file on disk: the database can always be rebuilt from the JSON files.
    con.execute("PRAGMA journal_mode=MEMORY")
    con.execute("PRAGMA synchronous=OFF")
    con.row_factory = sqlite3.Row
    return con
