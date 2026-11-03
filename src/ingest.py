"""Load the Yelp Open Dataset into a local SQLite database.

Reads the JSON-lines files one line at a time (never the whole file at
once), so it works on a laptop.

Usage (from the city-guide folder):
    python3 src/ingest.py                 # businesses, hours, categories, tips, checkins
    python3 src/ingest.py --only business # just one part
    python3 src/ingest.py --report        # print coverage by state and city

Creates data/yelp.db. Standard library only.
"""

import argparse
import json
import sqlite3
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "yelp.db"
FILES = {
    "business": DATA / "yelp_academic_dataset_business.json",
    "checkin": DATA / "yelp_academic_dataset_checkin.json",
    "tip": DATA / "yelp_academic_dataset_tip.json",
}
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    business_id TEXT PRIMARY KEY, name TEXT, address TEXT, city TEXT, state TEXT,
    postal_code TEXT, latitude REAL, longitude REAL, stars REAL, review_count INTEGER,
    is_open INTEGER, categories TEXT, attributes TEXT
);
CREATE TABLE IF NOT EXISTS categories (business_id TEXT, category TEXT);
-- open_min / close_min are minutes after midnight; close_min > 1440 means past midnight
CREATE TABLE IF NOT EXISTS hours (business_id TEXT, day INTEGER, open_min INTEGER, close_min INTEGER);
CREATE TABLE IF NOT EXISTS tips (business_id TEXT, user_id TEXT, text TEXT, date TEXT, compliment_count INTEGER);
-- day: 0=Monday .. 6=Sunday
CREATE TABLE IF NOT EXISTS checkin_hours (business_id TEXT, day INTEGER, hour INTEGER, n INTEGER);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS ix_biz_city ON businesses(state, city);
CREATE INDEX IF NOT EXISTS ix_cat ON categories(category, business_id);
CREATE INDEX IF NOT EXISTS ix_cat_biz ON categories(business_id);
CREATE INDEX IF NOT EXISTS ix_hours ON hours(business_id, day);
CREATE INDEX IF NOT EXISTS ix_tips ON tips(business_id);
CREATE INDEX IF NOT EXISTS ix_checkin ON checkin_hours(business_id, day, hour);
"""


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def to_minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse_categories(raw):
    # The docs show a list; the actual file uses a comma-separated string. Handle both.
    if not raw:
        return []
    if isinstance(raw, list):
        return [c.strip() for c in raw if c.strip()]
    return [c.strip() for c in raw.split(",") if c.strip()]


def load_business(con):
    con.executescript("DELETE FROM businesses; DELETE FROM categories; DELETE FROM hours;")
    biz_rows, cat_rows, hour_rows = [], [], []
    for b in read_lines(FILES["business"]):
        cats = parse_categories(b.get("categories"))
        biz_rows.append((
            b["business_id"], b.get("name"), b.get("address"), (b.get("city") or "").strip(),
            b.get("state"), b.get("postal_code"), b.get("latitude"), b.get("longitude"),
            b.get("stars"), b.get("review_count"), b.get("is_open"), ", ".join(cats),
            json.dumps(b.get("attributes") or {}),
        ))
        cat_rows.extend((b["business_id"], c) for c in cats)
        for day_name, span in (b.get("hours") or {}).items():
            if day_name not in DAYS or "-" not in span:
                continue
            start, end = span.split("-")
            o, c = to_minutes(start), to_minutes(end)
            if c <= o:  # closes after midnight, or "0:0-0:0" meaning open all day
                c += 1440
            hour_rows.append((b["business_id"], DAYS.index(day_name), o, c))
    con.executemany("INSERT INTO businesses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", biz_rows)
    con.executemany("INSERT INTO categories VALUES (?,?)", cat_rows)
    con.executemany("INSERT INTO hours VALUES (?,?,?,?)", hour_rows)
    return len(biz_rows)


def load_tip(con):
    con.execute("DELETE FROM tips")
    rows = ((t["business_id"], t.get("user_id"), t.get("text"), t.get("date"), t.get("compliment_count"))
            for t in read_lines(FILES["tip"]))
    con.executemany("INSERT INTO tips VALUES (?,?,?,?,?)", rows)
    return con.execute("SELECT COUNT(*) FROM tips").fetchone()[0]


def load_checkin(con):
    """Aggregate raw check-in timestamps into counts per business, weekday and hour."""
    con.execute("DELETE FROM checkin_hours")
    weekday_cache = {}
    total = 0
    for c in read_lines(FILES["checkin"]):
        counts = {}
        for ts in c.get("date", "").split(","):
            ts = ts.strip()
            if len(ts) < 13:
                continue
            d = ts[:10]
            wd = weekday_cache.get(d)
            if wd is None:
                wd = weekday_cache[d] = date(int(d[:4]), int(d[5:7]), int(d[8:10])).weekday()
            key = (wd, int(ts[11:13]))
            counts[key] = counts.get(key, 0) + 1
            total += 1
        con.executemany("INSERT INTO checkin_hours VALUES (?,?,?,?)",
                        [(c["business_id"], wd, hr, n) for (wd, hr), n in counts.items()])
    return total


def report(con):
    print("\nBusinesses by state (open / total):")
    for state, open_n, total in con.execute(
            "SELECT state, SUM(is_open), COUNT(*) FROM businesses GROUP BY state "
            "HAVING COUNT(*) >= 100 ORDER BY COUNT(*) DESC"):
        print(f"  {state:4} {open_n:>7,} / {total:>7,}")
    print("\nTop 20 cities (open businesses with 20+ reviews):")
    for city, state, n in con.execute(
            "SELECT city, state, COUNT(*) FROM businesses WHERE is_open=1 AND review_count>=20 "
            "GROUP BY city, state ORDER BY COUNT(*) DESC LIMIT 20"):
        print(f"  {city}, {state}: {n:,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["business", "tip", "checkin"])
    ap.add_argument("--report", action="store_true", help="only print the coverage report")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    # Keep the rollback journal in memory: no journal file is created or deleted.
    # The database is rebuildable from the JSON files, so this trade-off is safe.
    con.execute("PRAGMA journal_mode=MEMORY")
    con.execute("PRAGMA synchronous=OFF")
    con.executescript(SCHEMA)
    if not args.report:
        steps = [args.only] if args.only else ["business", "tip", "checkin"]
        loaders = {"business": load_business, "tip": load_tip, "checkin": load_checkin}
        for step in steps:
            t0 = time.time()
            n = loaders[step](con)
            con.commit()
            print(f"{step}: {n:,} rows in {time.time() - t0:.0f}s")
        con.executescript(INDEXES)
        con.commit()
    report(con)
    con.close()


if __name__ == "__main__":
    main()
