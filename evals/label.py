"""Label search results by hand: the ground truth every metric depends on.

For each query, results from every search method are pooled, de-duplicated and
shown in random order (so you can't tell which method found what). Grade each:
    great matches -> grade 2     okay matches -> grade 1     everything else -> 0

Progress is saved after every query, so you can stop and resume any time.
When a new search method is added, re-run this: you'll only see new candidates.

Usage:
    python3 evals/label.py --city Philadelphia
"""

import argparse
import json
import random
import textwrap

from common import methods_for, connect, labels_path, load_labels, load_queries, run

POOL_DEPTH = 10


def snippet(con, business_id, chars=220):
    row = con.execute("SELECT text FROM profiles WHERE business_id=?", (business_id,)).fetchone()
    return textwrap.shorten(row["text"], chars) if row else ""


def parse_numbers(text, n):
    nums = set()
    for tok in text.replace(",", " ").split():
        if tok.isdigit() and 1 <= int(tok) <= n:
            nums.add(int(tok))
    return nums


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="Philadelphia")
    args = ap.parse_args()

    con = connect()
    path = labels_path(args.city)
    labels = load_labels(path)
    queries = load_queries(args.city)

    for qi, q in enumerate(queries, 1):
        pool = {}
        for m in methods_for(args.city):
            for r in run(con, q, args.city, m, POOL_DEPTH):
                pool.setdefault(r["business_id"], r)
        todo = [r for bid, r in pool.items() if bid not in labels.get(q["id"], {})]
        if not todo:
            continue
        random.Random(q["id"]).shuffle(todo)

        extra = " ".join(f"{k}={q[k]}" for k in ("day", "time", "category") if q.get(k))
        print("\n" + "=" * 78)
        print(f"[{qi}/{len(queries)}] {q['id']}: \"{q['query']}\"  {extra}")
        print("=" * 78)
        for i, r in enumerate(todo, 1):
            print(f"{i:2}. {r['name']}  ({r['stars']}★, {r['review_count']} reviews)")
            print(f"    {textwrap.shorten(r['categories'] or '', 90)}")
            print(f"    {snippet(con, r['business_id'])}")

        great = input("\nGreat matches (numbers, e.g. 1 4) | s=skip | q=quit: ").strip().lower()
        if great == "q":
            break
        if great == "s":
            continue
        okay = input("Okay matches (numbers): ").strip()
        g2 = parse_numbers(great, len(todo))
        g1 = parse_numbers(okay, len(todo)) - g2
        with open(path, "a") as f:
            for i, r in enumerate(todo, 1):
                grade = 2 if i in g2 else 1 if i in g1 else 0
                f.write(json.dumps({"query_id": q["id"], "business_id": r["business_id"],
                                    "name": r["name"], "grade": grade}) + "\n")
                labels.setdefault(q["id"], {})[r["business_id"]] = grade
        print(f"saved {len(todo)} labels for {q['id']}")

    done = sum(1 for q in queries if labels.get(q["id"]))
    print(f"\nLabeled queries: {done}/{len(queries)}  (file: {path.name})")


if __name__ == "__main__":
    main()
