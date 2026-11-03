"""Look inside the vector database.

Usage:
    python3 src/inspect_vectors.py info                            # what's in it, what a vector looks like
    python3 src/inspect_vectors.py similar "Reading Terminal Market"  # nearest neighbors of one business
    python3 src/inspect_vectors.py compare "cozy cafe" "quiet coffee shop" "sports bar"
"""

import argparse
from pathlib import Path

from embedder import embed, load_store, store_path


def cmd_info(city):
    store = load_store(city)
    folder = store_path(city)
    print(f"Vector database for {city}: {folder}\n")
    for f in sorted(Path(folder).iterdir()):
        print(f"  {f.name:15} {f.stat().st_size / 1e6:8.2f} MB")
    info = store.info()
    print(f"\n  model:  {info['model']}")
    print(f"  rows:   {info['count']:,} businesses")
    print(f"  dims:   {info['dim']} numbers per business")
    print(f"  matrix: {info['count']:,} x {info['dim']} float32 = {info['megabytes']} MB in memory")
    print(f"\nRow 0 is {store.records[0]['name']!r}. Its first 8 of {info['dim']} numbers:")
    print("  " + "  ".join(f"{x:+.3f}" for x in store.vectors[0][:8]) + "  ...")
    print("  (each number alone means nothing; the direction of the whole vector carries the meaning)")


def cmd_similar(city, name, k):
    store = load_store(city)
    matches = [i for i, r in enumerate(store.records) if r["name"].lower() == name.lower()]
    if not matches:
        matches = [i for i, r in enumerate(store.records) if name.lower() in r["name"].lower()]
    if not matches:
        raise SystemExit(f"No business named like {name!r} in the {city} store.")
    i = matches[0]
    print(f"Most similar to {store.records[i]['name']!r} ({store.records[i]['categories']}):\n")
    for score, _, r in store.search(store.vectors[i], k=k + 1)[1:]:
        print(f"  {score:.3f}  {r['name']}  ({r['categories'][:70]})")


def cmd_compare(phrases):
    vecs = embed(phrases)
    width = max(len(p) for p in phrases)
    print("Cosine similarity (1.0 = same meaning, near 0 = unrelated):\n")
    print(" " * (width + 2) + "  ".join(f"{j + 1:>6}" for j in range(len(phrases))))
    for i, p in enumerate(phrases):
        row = "  ".join(f"{float(vecs[i] @ vecs[j]):6.3f}" for j in range(len(phrases)))
        print(f"{p:>{width}}  {row}   ({i + 1})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["info", "similar", "compare"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--city", default="Philadelphia")
    ap.add_argument("-k", type=int, default=10)
    a = ap.parse_args()
    if a.command == "info":
        cmd_info(a.city)
    elif a.command == "similar":
        cmd_similar(a.city, " ".join(a.args), a.k)
    else:
        cmd_compare(a.args or ["cozy cafe", "quiet coffee shop", "sports bar", "place to watch football"])


if __name__ == "__main__":
    main()
