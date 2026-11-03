"""Shared helpers for the evals."""

import json
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS.parent / "src"))

from db import DAYS, connect  # noqa: E402
from search import parse_time, search  # noqa: E402

METHODS = ["popular", "keyword"]   # add "vector" and "hybrid" in week 3


def load_queries(city):
    path = EVALS / f"queries_{city.lower().replace(' ', '_')}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def labels_path(city):
    return EVALS / f"labels_{city.lower().replace(' ', '_')}.jsonl"


def load_labels(path):
    """{query_id: {business_id: grade}}. Later lines override earlier ones."""
    labels = {}
    if Path(path).exists():
        for line in Path(path).read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                labels.setdefault(r["query_id"], {})[r["business_id"]] = r["grade"]
    return labels


def run(con, q, city, method, k):
    day = DAYS.index(q["day"]) if q.get("day") else None
    minute = parse_time(q["time"]) if q.get("time") else None
    return search(con, q["query"], city, k=k, method=method, day=day, minute=minute,
                  category=q.get("category"))
