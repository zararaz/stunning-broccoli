"""Candidate retrieval: structured filters plus keyword search (BM25).

Four methods, so they can be compared in the evals:
  popular - filters only, ranked by a quality score (ratings + review count)
  keyword - BM25 text relevance over business profiles, blended with quality
  vector  - meaning similarity from the vector database, blended with quality
            (needs: pip install -r requirements.txt, then src/build_vectors.py)
  hybrid  - keyword + vector + quality together

Usage:
    python3 src/search.py --build                       # build the keyword index once
    python3 src/search.py "quiet cafe to work" --city Philadelphia
    python3 src/search.py "brunch with outdoor seating" --city Philadelphia --day Sunday --time 11:00
    python3 src/search.py "" --city Philadelphia --category "Museums" --method popular
    python3 src/search.py "cozy spot to read" --method vector
"""

import argparse
import math
import re
import time

from db import DAYS, connect

STOPWORDS = set("""a an and are as at be best but by can for from good great go
how i in is it me my near of on or place places some spot spots that the
there to want where which with you your""".split())

TEXT_WEIGHT = 0.7       # share of the final score from text relevance (keyword method)
PRIOR_REVIEWS = 20      # Bayesian rating: how many "average" reviews each place starts with
MIN_REVIEWS = 10


def build_index(con):
    con.executescript("""
        DROP TABLE IF EXISTS profiles_fts;
        CREATE VIRTUAL TABLE profiles_fts USING fts5(
            business_id UNINDEXED, city UNINDEXED, text, tokenize='porter unicode61');
        INSERT INTO profiles_fts (business_id, city, text) SELECT business_id, city, text FROM profiles;
    """)
    con.commit()


def to_fts_query(text):
    """Natural-language query -> FTS5 OR-query of meaningful words."""
    words = [w for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in STOPWORDS and len(w) > 1]
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(words))


def parse_time(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def open_at(con, business_id, day, minute):
    """True if open on `day` (0=Mon) at `minute` after midnight, including after-midnight spans
    from the previous day. Businesses with no hours listed count as not open."""
    prev = (day - 1) % 7
    row = con.execute(
        "SELECT 1 FROM hours WHERE business_id=? AND ("
        " (day=? AND open_min<=? AND close_min>?) OR (day=? AND close_min>?)) LIMIT 1",
        (business_id, day, minute, minute, prev, minute + 1440)).fetchone()
    return row is not None


def open_ids(con, day, minute):
    """Every business open on `day` at `minute`, in one query (same rules as open_at)."""
    prev = (day - 1) % 7
    return {r[0] for r in con.execute(
        "SELECT DISTINCT business_id FROM hours WHERE "
        "(day=? AND open_min<=? AND close_min>?) OR (day=? AND close_min>?)",
        (day, minute, minute, prev, minute + 1440))}


def quality(stars, n, city_mean):
    """0..1 score: Bayesian-averaged rating, nudged up by review volume."""
    bayes = (PRIOR_REVIEWS * city_mean + stars * n) / (PRIOR_REVIEWS + n)
    volume = min(1.0, math.log10(1 + n) / 3)       # saturates at ~1,000 reviews
    return max(0.0, (bayes - 1) / 4) * (0.7 + 0.3 * volume)


def search(con, query, city, k=10, method="keyword", day=None, minute=None,
           category=None, min_reviews=MIN_REVIEWS, pool=500):
    """Return up to k candidates as dicts, best first."""
    city_mean = con.execute("SELECT AVG(stars) FROM businesses WHERE city=?", (city,)).fetchone()[0] or 3.5

    # 1. Structured filters: the same for every method.
    filters = ["b.city = ?", "b.is_open = 1", "b.review_count >= ?"]
    params = [city, min_reviews]
    if category:
        filters.append("b.business_id IN (SELECT business_id FROM categories WHERE category = ?)")
        params.append(category)
    rows = con.execute(f"SELECT b.* FROM businesses b WHERE {' AND '.join(filters)}", params).fetchall()
    if day is not None and minute is not None:
        is_open = open_ids(con, day, minute)
        rows = [r for r in rows if r["business_id"] in is_open]

    # 2. Text relevance signals, depending on the method.
    keyword, vector = {}, {}
    fts = to_fts_query(query) if method in ("keyword", "hybrid") else ""
    if fts:
        keyword = {r[0]: r[1] for r in con.execute(
            "SELECT business_id, -bm25(profiles_fts) FROM profiles_fts "
            "WHERE profiles_fts MATCH ? AND city = ? ORDER BY bm25(profiles_fts) LIMIT ?",
            (fts, city, pool * 4))}
    if method in ("vector", "hybrid") and query.strip():
        from embedder import vector_scores
        vector = vector_scores(city, query)

    if method == "keyword" and keyword:
        rows = [r for r in rows if r["business_id"] in keyword]
    if method == "vector" and vector:
        rows = [r for r in rows if r["business_id"] in vector]
    if not rows:
        return []

    # 3. Put each signal on a 0..1 scale across the candidates, then blend.
    ids = [r["business_id"] for r in rows]
    kw_max = max((keyword.get(i, 0) for i in ids), default=0) or 1.0
    v_vals = [vector[i] for i in ids if i in vector]
    v_min, v_max = (min(v_vals), max(v_vals)) if v_vals else (0.0, 1.0)
    v_span = (v_max - v_min) or 1.0

    results = []
    for r in rows:
        bid = r["business_id"]
        q = quality(r["stars"], r["review_count"], city_mean)
        kw = keyword.get(bid, 0) / kw_max
        vs = (vector[bid] - v_min) / v_span if bid in vector else 0.0
        if method == "keyword" and keyword:
            score = TEXT_WEIGHT * kw + (1 - TEXT_WEIGHT) * q
        elif method == "vector" and vector:
            score = TEXT_WEIGHT * vs + (1 - TEXT_WEIGHT) * q
        elif method == "hybrid" and (keyword or vector):
            score = TEXT_WEIGHT / 2 * kw + TEXT_WEIGHT / 2 * vs + (1 - TEXT_WEIGHT) * q
        else:
            score = q
        results.append({
            "business_id": bid, "name": r["name"], "address": r["address"],
            "stars": r["stars"], "review_count": r["review_count"], "categories": r["categories"],
            "latitude": r["latitude"], "longitude": r["longitude"],
            "score": round(score, 4), "keyword": round(kw, 4), "vector": round(vs, 4),
            "quality": round(q, 4),
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--city", default="Philadelphia")
    ap.add_argument("--method", choices=["popular", "keyword", "vector", "hybrid"], default="keyword")
    ap.add_argument("--day", choices=DAYS)
    ap.add_argument("--time", help="HH:MM, 24-hour clock")
    ap.add_argument("--category")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--build", action="store_true", help="(re)build the keyword index")
    args = ap.parse_args()

    con = connect()
    if args.build:
        t0 = time.time()
        build_index(con)
        print(f"keyword index built in {time.time() - t0:.0f}s")
        return
    day = DAYS.index(args.day) if args.day else None
    minute = parse_time(args.time) if args.time else None
    for i, r in enumerate(search(con, args.query, args.city, args.k, args.method, day, minute,
                                 args.category), 1):
        print(f"{i:2}. {r['name']}  ({r['stars']}★, {r['review_count']} reviews)  score={r['score']}")
        print(f"    {r['categories']}")


if __name__ == "__main__":
    main()
