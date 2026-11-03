"""Build one searchable text profile per business.

A profile combines the name, categories, readable attributes (wifi, noise,
price, ambience...) and the most-complimented tips. The same text feeds
keyword search now and embeddings later.

Usage:
    python3 src/profiles.py                    # all cities
    python3 src/profiles.py --city Philadelphia
"""

import argparse
import ast
import json
import time

from db import connect

TIPS_PER_BUSINESS = 5
TIP_CHARS = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (business_id TEXT PRIMARY KEY, city TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_profiles_city ON profiles(city);
"""


def parse_value(raw):
    """Yelp stores attribute values as Python-literal strings, e.g. "u'free'" or "{'romantic': False}"."""
    if not isinstance(raw, str):
        return raw
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw


def true_keys(d):
    return [k for k, v in (d or {}).items() if v is True] if isinstance(d, dict) else []


def describe_attributes(attrs):
    a = {k: parse_value(v) for k, v in attrs.items()}
    out = []
    if a.get("WiFi") == "free":
        out.append("free wifi")
    noise = a.get("NoiseLevel")
    if isinstance(noise, str) and noise not in ("None",):
        out.append({"quiet": "quiet", "average": "average noise", "loud": "loud",
                    "very_loud": "very loud"}.get(noise, noise))
    price = a.get("RestaurantsPriceRange2")
    if price in (1, 2, 3, 4) or (isinstance(price, str) and price.isdigit()):
        out.append("price " + "$" * int(price) + (" cheap" if int(price) == 1 else ""))
    flags = {
        "OutdoorSeating": "outdoor seating", "GoodForKids": "good for kids",
        "RestaurantsGoodForGroups": "good for groups", "DogsAllowed": "dog friendly",
        "HappyHour": "happy hour", "BYOB": "byob", "RestaurantsReservations": "takes reservations",
        "RestaurantsTakeOut": "takeout", "WheelchairAccessible": "wheelchair accessible",
        "HasTV": "has tv", "GoodForDancing": "good for dancing",
    }
    out += [label for key, label in flags.items() if a.get(key) is True]
    alcohol = a.get("Alcohol")
    if alcohol == "full_bar":
        out.append("full bar")
    elif alcohol == "beer_and_wine":
        out.append("beer and wine")
    ambience = true_keys(a.get("Ambience"))
    if ambience:
        out.append("ambience: " + ", ".join(ambience))
    meals = true_keys(a.get("GoodForMeal"))
    if meals:
        out.append("good for: " + ", ".join(meals))
    music = true_keys(a.get("Music"))
    if music:
        out.append("music: " + ", ".join(m.replace("_", " ") for m in music))
    return out


def build(con, city=None):
    con.executescript(SCHEMA)
    where, params = ("WHERE city = ?", [city]) if city else ("", [])
    if city:
        con.execute("DELETE FROM profiles WHERE city = ?", [city])
    else:
        con.execute("DELETE FROM profiles")

    rows = con.execute(f"SELECT business_id, name, city, categories, attributes FROM businesses {where}",
                       params).fetchall()
    ids = [r["business_id"] for r in rows]

    # Top tips per business, most complimented first, then newest.
    tips = {}
    for i in range(0, len(ids), 900):
        chunk = ids[i:i + 900]
        marks = ",".join("?" * len(chunk))
        for t in con.execute(
                f"SELECT business_id, text FROM tips WHERE business_id IN ({marks}) "
                f"ORDER BY business_id, compliment_count DESC, date DESC", chunk):
            lst = tips.setdefault(t["business_id"], [])
            if len(lst) < TIPS_PER_BUSINESS:
                lst.append(" ".join(t["text"].split())[:TIP_CHARS].rstrip(" .!"))

    out = []
    for r in rows:
        parts = [r["name"], r["categories"] or ""]
        parts += describe_attributes(json.loads(r["attributes"] or "{}"))
        parts += tips.get(r["business_id"], [])
        out.append((r["business_id"], r["city"], ". ".join(p for p in parts if p)))
    con.executemany("INSERT INTO profiles VALUES (?,?,?)", out)
    con.commit()
    return len(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city")
    args = ap.parse_args()
    con = connect()
    t0 = time.time()
    n = build(con, args.city)
    print(f"profiles: {n:,} built in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
