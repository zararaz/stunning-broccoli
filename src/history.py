"""App state: what each user has already been recommended.

Kept in its own database (data/app.db), separate from the Yelp data, so the
dataset can be rebuilt without losing anyone's history. Set CITY_GUIDE_APP_DB
to use another file.
"""

import os
import time
from pathlib import Path

from db import ROOT, connect

APP_DB = Path(os.environ.get("CITY_GUIDE_APP_DB", ROOT / "data" / "app.db"))


def _con():
    APP_DB.parent.mkdir(parents=True, exist_ok=True)
    con = connect(APP_DB)
    con.execute("CREATE TABLE IF NOT EXISTS picks (user_id TEXT, city TEXT, mode TEXT, business_id TEXT, "
                "name TEXT, categories TEXT, picked_at TEXT)")
    return con


def previous(user_id, city, modes=("weekly", "explore")):
    """This user's past picks in this city, newest first."""
    marks = ",".join("?" * len(modes))
    with _con() as con:
        rows = con.execute(f"SELECT * FROM picks WHERE user_id=? AND city=? AND mode IN ({marks}) "
                           f"ORDER BY picked_at DESC, rowid DESC", (user_id, city, *modes)).fetchall()
    return [dict(r) for r in rows]


def record(user_id, city, mode, stops):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with _con() as con:
        con.executemany("INSERT INTO picks VALUES (?,?,?,?,?,?,?)",
                        [(user_id, city, mode, s["business_id"], s["name"], s["categories"], now) for s in stops])
