"""Step 2: turn a Request into a Plan, using plain code (no LLM).

    visit    a one-day itinerary: breakfast -> sight -> lunch -> afternoon ->
             dinner -> evening, each stop open at its time and close to the last
    explore  a resident's list: places to eat this week, and things to do this month
    weekly   one new restaurant, never repeated, varying the cuisine

Retrieval comes from search.py. The planner adds the rules a list of search
results can't express: opening times, walking distance, variety, no repeats.
"""

import importlib.util
import json
import math

from embedder import has_vectors
from profiles import parse_value
from search import parse_time, search

MAX_LEG_KM = 5.0          # longest hop between itinerary stops before it's flagged
DIST_PENALTY = 0.04       # score lost per km from the previous stop

# (slot, label, time, search words, allowed categories, which interests to add)
VISIT_SLOTS = [
    ("breakfast", "Breakfast", "09:00", "breakfast coffee brunch bakery",
     {"Breakfast & Brunch", "Coffee & Tea", "Bakeries", "Cafes"}, "food"),
    ("morning", "Morning", "10:30", "museum history art landmark",
     {"Museums", "Art Museums", "Landmarks & Historical Buildings", "Art Galleries", "Parks", "Tours"}, "activities"),
    ("lunch", "Lunch", "12:30", "lunch sandwiches",
     {"Restaurants", "Sandwiches", "Delis", "Food Stands", "Public Markets"}, "food"),
    ("afternoon", "Afternoon", "14:30", "park market shopping gallery",
     {"Parks", "Public Markets", "Shopping", "Art Galleries", "Museums", "Botanical Gardens", "Bookstores"}, "activities"),
    ("dinner", "Dinner", "18:30", "dinner restaurant",
     {"Restaurants"}, "food"),
    ("evening", "Evening", "21:00", "bar cocktails live music",
     {"Bars", "Cocktail Bars", "Wine Bars", "Music Venues", "Jazz & Blues", "Pubs", "Breweries"}, "activities"),
]

# (section, search words, allowed categories, how many, which interests)
EXPLORE_SECTIONS = [
    ("Eat this week", "restaurant dinner", {"Restaurants"}, 2, "food"),
    ("Coffee spot", "coffee cafe", {"Coffee & Tea", "Cafes"}, 1, "food"),
    ("Outdoors this month", "park garden trail", {"Parks", "Botanical Gardens", "Hiking", "Gardens"}, 1, "activities"),
    ("Culture this month", "museum gallery history", {"Museums", "Art Museums", "Art Galleries",
                                                       "Landmarks & Historical Buildings", "Performing Arts"}, 1, "activities"),
    ("Night out", "bar live music cocktails", {"Bars", "Cocktail Bars", "Music Venues", "Jazz & Blues"}, 1, "activities"),
]

# Categories too broad to count as a cuisine when varying weekly picks.
GENERIC = {"Restaurants", "Food", "Nightlife", "Bars", "Event Planning & Services", "Caterers",
           "Food Delivery Services", "Breakfast & Brunch", "American (New)", "American (Traditional)"}


def search_method(city):
    """Hybrid search when the vector database and its libraries exist, else keyword."""
    libs = all(importlib.util.find_spec(m) for m in ("numpy", "sentence_transformers"))
    return "hybrid" if has_vectors(city) and libs else "keyword"


def km(a, b):
    """Great-circle distance between two stops, in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def price_level(con, business_id):
    row = con.execute("SELECT attributes FROM businesses WHERE business_id=?", (business_id,)).fetchone()
    value = parse_value(json.loads(row["attributes"] or "{}").get("RestaurantsPriceRange2"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def candidates(con, req, words, allowed, interests, method, exclude, day=None, minute=None, k=80):
    query = " ".join([words] + interests)
    results = search(con, query, req.city, k=k, method=method, day=day, minute=minute)
    keep = []
    for r in results:
        cats = {c.strip() for c in (r["categories"] or "").split(",")}
        if not cats & allowed or r["business_id"] in exclude:
            continue
        if req.budget and "Restaurants" in allowed:
            p = price_level(con, r["business_id"])
            if p and ((req.budget == "low" and p > 2) or (req.budget == "high" and p < 3)):
                continue
        keep.append(r)
    return keep


def stop_from(r, **extra):
    keys = ("business_id", "name", "address", "categories", "stars", "review_count", "latitude", "longitude")
    return {**{k: r[k] for k in keys}, **extra}


def plan_visit(con, req, method):
    day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].index(req.day)
    stops, used, prev = [], set(), None
    for slot, label, time, words, allowed, kind in VISIT_SLOTS:
        cands = candidates(con, req, words, allowed, getattr(req, kind), method, used,
                           day=day, minute=parse_time(time))
        if not cands:
            continue
        if prev:   # prefer places near the previous stop
            cands.sort(key=lambda r: r["score"] - DIST_PENALTY * min(km(prev, r), 2 * MAX_LEG_KM), reverse=True)
        best = cands[0]
        stops.append(stop_from(best, slot=slot, label=label, time=time,
                               km_from_previous=round(km(prev, best), 2) if prev else None))
        used.add(best["business_id"])
        prev = best
    return {"mode": "visit", "city": req.city, "day": req.day, "stops": stops}


def plan_explore(con, req, method, exclude):
    sections, used = [], set(exclude)
    for title, words, allowed, n, kind in EXPLORE_SECTIONS:
        picks = candidates(con, req, words, allowed, getattr(req, kind), method, used)[:n]
        used.update(p["business_id"] for p in picks)
        if picks:
            sections.append({"title": title, "stops": [stop_from(p) for p in picks]})
    return {"mode": "explore", "city": req.city, "sections": sections}


def cuisines(categories):
    return {c.strip() for c in (categories or "").split(",")} - GENERIC


def plan_weekly(con, req, method, history):
    tried = {h["business_id"] for h in history}
    recent = set().union(*[cuisines(h["categories"]) for h in history[:3]]) if history else set()
    cands = candidates(con, req, "restaurant dinner", {"Restaurants"}, req.food, method, tried)
    fresh = [c for c in cands if not cuisines(c["categories"]) & recent]
    pick = (fresh or cands or [None])[0]
    return {"mode": "weekly", "city": req.city, "week": len(history) + 1,
            "pick": stop_from(pick) if pick else None, "avoided_cuisines": sorted(recent)}


def plan_stops(plan):
    """Every stop in a plan, whatever its shape."""
    if plan["mode"] == "visit":
        return plan["stops"]
    if plan["mode"] == "explore":
        return [s for sec in plan["sections"] for s in sec["stops"]]
    return [plan["pick"]] if plan.get("pick") else []


def validate(con, plan):
    """Independent checks on the finished plan. Never trust the step that built it."""
    from search import open_at
    issues = []
    ids = [s["business_id"] for s in plan_stops(plan)]
    if not ids:
        issues.append("no places found for this request")
    if len(ids) != len(set(ids)):
        issues.append("a place appears twice")
    for s in plan_stops(plan):
        row = con.execute("SELECT is_open FROM businesses WHERE business_id=?", (s["business_id"],)).fetchone()
        if not row or not row["is_open"]:
            issues.append(f"{s['name']} is not an open business in the data")
    if plan["mode"] == "visit":
        day = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].index(plan["day"])
        for s in plan["stops"]:
            if not open_at(con, s["business_id"], day, parse_time(s["time"])):
                issues.append(f"{s['name']} may be closed at {s['time']}")
            if s["km_from_previous"] and s["km_from_previous"] > MAX_LEG_KM:
                issues.append(f"{s['name']} is {s['km_from_previous']} km from the previous stop")
        missing = {slot for slot, *_ in VISIT_SLOTS} - {s["slot"] for s in plan["stops"]}
        if missing:
            issues.append("nothing open found for: " + ", ".join(sorted(missing)))
    return issues
