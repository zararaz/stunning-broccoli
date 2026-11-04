"""Scaling lab: how do different vector indexes behave as the data grows?

For each data size it builds every index, runs the same queries, and measures:
  build_s    seconds to build the index
  mem_MB     memory the index needs
  ms/query   median time for one query (single thread, like a web request)
  recall@10  share of the true top 10 (from exact search) the index returned

Methods:
  exact        brute force with numpy: our vectordb.py
  ivf          our from-scratch IVF index (src/ivf.py), several nprobe values
  faiss-flat   FAISS exact search (optimized brute force)
  faiss-ivf    FAISS IndexIVFFlat, same settings as ours
  faiss-hnsw   FAISS HNSW graph index, several efSearch values

Queries are real business vectors held out of the database, so every query
has meaningful neighbors.

Usage:
    python bench/scale_bench.py                      # Philadelphia: 1k, 2.5k, 5k, all
    python bench/scale_bench.py --store all          # after: make vectors-all
    python bench/scale_bench.py --sizes 1000,5000
"""

import argparse
import csv
import math
import statistics
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from embedder import store_path  # noqa: E402
from ivf import IVFIndex, top_k  # noqa: E402
from vectordb import VectorStore  # noqa: E402

K = 10
NPROBES = [1, 4, 16, 64]
EF_SEARCH = [16, 64, 256]


def recall(found, truth):
    return len(set(found[:K]) & set(truth)) / len(truth)


def timed_queries(search_one, queries, truth):
    """Run each query alone; return (median ms, mean recall)."""
    times, recalls = [], []
    for q, t in zip(queries, truth):
        t0 = time.perf_counter()
        ids = search_one(q)
        times.append((time.perf_counter() - t0) * 1000)
        recalls.append(recall(list(ids), t))
    return statistics.median(times), sum(recalls) / len(recalls)


def bench_size(base, queries, faiss):
    n, d = base.shape
    rows = []

    def record(method, params, build_s, mem_bytes, ms, rec):
        rows.append({"n": n, "method": method, "params": params, "build_s": round(build_s, 3),
                     "mem_MB": round(mem_bytes / 1e6, 2), "ms_per_query": round(ms, 3),
                     "recall@10": round(rec, 4)})

    # Ground truth and the exact baseline: compare with every vector.
    truth = [list(top_k(base @ q, K)) for q in queries]
    ms, rec = timed_queries(lambda q: top_k(base @ q, K), queries, truth)
    record("exact", "numpy", 0.0, base.nbytes, ms, rec)

    n_lists = max(8, int(4 * math.sqrt(n)))   # common rule of thumb: ~4 x sqrt(N) lists
    t0 = time.perf_counter()
    ivf = IVFIndex(n_lists).train(base).add(base)
    build = time.perf_counter() - t0
    for p in NPROBES:
        if p > n_lists:
            continue
        ms, rec = timed_queries(lambda q: ivf.search(q, K, p)[0], queries, truth)
        record("ivf", f"lists={n_lists} nprobe={p}", build, ivf.nbytes(), ms, rec)

    if faiss is None:
        return rows

    def faiss_bytes(index):
        return faiss.serialize_index(index).nbytes

    def faiss_search(index):
        return lambda q: index.search(q.reshape(1, -1), K)[1][0]

    t0 = time.perf_counter()
    flat = faiss.IndexFlatIP(d)
    flat.add(base)
    ms, rec = timed_queries(faiss_search(flat), queries, truth)
    record("faiss-flat", "exact", time.perf_counter() - t0, faiss_bytes(flat), ms, rec)

    t0 = time.perf_counter()
    quantizer = faiss.IndexFlatIP(d)
    fivf = faiss.IndexIVFFlat(quantizer, d, n_lists, faiss.METRIC_INNER_PRODUCT)
    fivf.train(base)
    fivf.add(base)
    build = time.perf_counter() - t0
    for p in NPROBES:
        if p > n_lists:
            continue
        fivf.nprobe = p
        ms, rec = timed_queries(faiss_search(fivf), queries, truth)
        record("faiss-ivf", f"lists={n_lists} nprobe={p}", build, faiss_bytes(fivf), ms, rec)

    t0 = time.perf_counter()
    hnsw = faiss.IndexHNSWFlat(d, 32, faiss.METRIC_INNER_PRODUCT)
    hnsw.hnsw.efConstruction = 64
    hnsw.add(base)
    build = time.perf_counter() - t0
    for ef in EF_SEARCH:
        hnsw.hnsw.efSearch = ef
        ms, rec = timed_queries(faiss_search(hnsw), queries, truth)
        record("faiss-hnsw", f"M=32 efSearch={ef}", build, faiss_bytes(hnsw), ms, rec)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default="philadelphia", help="folder under data/vectors/")
    ap.add_argument("--sizes", help="comma-separated database sizes, e.g. 1000,5000")
    ap.add_argument("--queries", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    try:
        import faiss
        faiss.omp_set_num_threads(1)   # single thread: a fair, per-request comparison
    except ImportError:
        faiss = None
        print("FAISS not installed: running only our own indexes (pip install faiss-cpu)\n")

    store = VectorStore.load(store_path(args.store))
    vectors = store.vectors.astype(np.float32)
    rng = np.random.default_rng(args.seed)
    perm = rng.permutation(len(vectors))
    queries = vectors[perm[:args.queries]]
    pool = vectors[perm[args.queries:]]                # queries are never in the database

    if args.sizes:
        sizes = [int(s) for s in args.sizes.split(",")]
    else:
        sizes = [s for s in (1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000) if s < len(pool)]
        sizes.append(len(pool))
    sizes = [s for s in sizes if s <= len(pool)]

    print(f"store={args.store} ({len(vectors):,} vectors x {vectors.shape[1]} dims), "
          f"{len(queries)} held-out queries, k={K}\n")
    header = f"{'n':>8}  {'method':11} {'params':24} {'build_s':>8} {'mem_MB':>8} {'ms/query':>9} {'recall@10':>9}"
    all_rows = []
    for n in sizes:
        print(header)
        for r in bench_size(np.ascontiguousarray(pool[:n]), queries, faiss):
            all_rows.append(r)
            print(f"{r['n']:>8,}  {r['method']:11} {r['params']:24} {r['build_s']:8.2f} "
                  f"{r['mem_MB']:8.2f} {r['ms_per_query']:9.3f} {r['recall@10']:9.3f}")
        print()

    out = ROOT / "bench" / "results"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"scale_{args.store}_{time.strftime('%Y%m%d-%H%M')}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)
    print(f"saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
