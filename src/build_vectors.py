"""Build the vector database for one city.

Embeds each business profile (built by profiles.py) and saves the store to
data/vectors/<city>/. Only open businesses with 10+ reviews are included,
matching what search returns.

Usage:
    python3 src/build_vectors.py --city Philadelphia
    python3 src/build_vectors.py --city all      # every city (~10x more), for the scaling lab
"""

import argparse
import time

from db import connect
from embedder import DEFAULT_MODEL, embed, store_path
from search import MIN_REVIEWS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="Philadelphia")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--min-reviews", type=int, default=MIN_REVIEWS)
    args = ap.parse_args()

    from vectordb import VectorStore

    con = connect()
    everywhere = args.city.lower() == "all"
    rows = con.execute(
        "SELECT b.business_id, b.name, b.categories, b.stars, b.review_count, b.latitude, b.longitude, p.text "
        "FROM businesses b JOIN profiles p USING(business_id) "
        f"WHERE {'1=1' if everywhere else 'b.city = ?'} AND b.is_open = 1 AND b.review_count >= ? "
        "ORDER BY b.business_id",
        ((args.min_reviews,) if everywhere else (args.city, args.min_reviews))).fetchall()
    if not rows:
        raise SystemExit(f"No profiles for {args.city}. Run src/profiles.py first.")
    print(f"{args.city}: {len(rows):,} business profiles to embed with {args.model}")

    t0 = time.time()
    vectors = embed([r["text"] for r in rows], args.model, progress=True)
    secs = time.time() - t0

    store = VectorStore(vectors.shape[1], args.model)
    store.add([r["business_id"] for r in rows], vectors,
              [{k: r[k] for k in ("name", "categories", "stars", "review_count", "latitude", "longitude")}
               for r in rows])
    out = store_path(args.city)
    store.save(out)

    info = store.info()
    print(f"\nembedded {info['count']:,} profiles in {secs:.0f}s ({info['count'] / secs:,.0f} per second)")
    print(f"vectors: {info['count']:,} x {info['dim']} = {info['megabytes']} MB")
    print(f"saved to {out.relative_to(out.parents[2])}/")


if __name__ == "__main__":
    main()
