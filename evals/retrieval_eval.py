"""Score each search method against your hand labels.

Metrics (all at k=10, averaged over labeled queries):
  P@10    share of the top 10 that are relevant (grade >= 1)
  R@10    share of all known relevant results that appear in the top 10
  nDCG@10 ranking quality using grades, 1.0 = perfect order
  MRR     1 / rank of the first relevant result
  judged  share of the top 10 you have labeled; low means re-run label.py

Usage:
    python3 evals/retrieval_eval.py --city Philadelphia
"""

import argparse
import json
import math
import time

from common import methods_for, EVALS, connect, labels_path, load_labels, load_queries, run

K = 10


def dcg(grades):
    return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def score_query(ranked_ids, judged):
    grades = [judged.get(b, 0) for b in ranked_ids[:K]]
    relevant_total = sum(1 for g in judged.values() if g >= 1)
    ideal = dcg(sorted(judged.values(), reverse=True)[:K])
    first = next((i for i, g in enumerate(grades, 1) if g >= 1), None)
    return {
        "P@10": sum(g >= 1 for g in grades) / K,
        "R@10": (sum(g >= 1 for g in grades) / relevant_total) if relevant_total else 0.0,
        "nDCG@10": dcg(grades) / ideal if ideal else 0.0,
        "MRR": 1 / first if first else 0.0,
        "judged": sum(b in judged for b in ranked_ids[:K]) / K,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="Philadelphia")
    ap.add_argument("--labels", help="labels file (default: evals/labels_<city>.jsonl)")
    args = ap.parse_args()

    con = connect()
    labels = load_labels(args.labels or labels_path(args.city))
    queries = [q for q in load_queries(args.city) if labels.get(q["id"])]
    if not queries:
        print("No labeled queries yet. Run: python3 evals/label.py")
        return

    summary = {}
    print(f"{len(queries)} labeled queries, k={K}\n")
    print(f"{'method':10} {'P@10':>6} {'R@10':>6} {'nDCG@10':>8} {'MRR':>6} {'judged':>7} {'ms/query':>9}")
    for m in methods_for(args.city):
        totals, t0 = {}, time.time()
        for q in queries:
            ranked = [r["business_id"] for r in run(con, q, args.city, m, K)]
            for key, v in score_query(ranked, labels[q["id"]]).items():
                totals[key] = totals.get(key, 0) + v
        ms = (time.time() - t0) * 1000 / len(queries)
        avg = {key: v / len(queries) for key, v in totals.items()}
        summary[m] = {**avg, "ms_per_query": ms}
        print(f"{m:10} {avg['P@10']:6.3f} {avg['R@10']:6.3f} {avg['nDCG@10']:8.3f} "
              f"{avg['MRR']:6.3f} {avg['judged']:7.0%} {ms:9.0f}")

    out = EVALS / "results"
    out.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    (out / f"retrieval_{args.city.lower()}_{stamp}.json").write_text(json.dumps(
        {"city": args.city, "queries": len(queries), "k": K, "methods": summary}, indent=2))


if __name__ == "__main__":
    main()
