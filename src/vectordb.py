"""A minimal vector database, written to be read and understood.

On disk it is just a folder of plain files:
    manifest.json   which model made the vectors, how many, how many dimensions
    vectors.npy     an N x D matrix of float32 numbers, one row per record
    records.jsonl   one line per row: the record's id and its metadata

Search is exact ("brute force"): the query vector is compared with every
row using cosine similarity, which for normalized vectors is a dot product.
That is fast for thousands of rows; approximate indexes (IVF, HNSW) are
what make millions of rows fast, and come later.
"""

import json
import time
from pathlib import Path

import numpy as np


def normalize(m):
    m = np.asarray(m, dtype=np.float32)
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    return m / np.maximum(norms, 1e-12)


class VectorStore:
    def __init__(self, dim, model=None):
        self.dim = dim
        self.model = model
        self.vectors = np.zeros((0, dim), dtype=np.float32)
        self.ids = []
        self.records = []

    def __len__(self):
        return len(self.ids)

    def add(self, ids, vectors, records):
        vectors = normalize(vectors)
        if vectors.shape[1] != self.dim:
            raise ValueError(f"expected {self.dim} dimensions, got {vectors.shape[1]}")
        self.vectors = np.vstack([self.vectors, vectors])
        self.ids.extend(ids)
        self.records.extend(records)

    def scores(self, query_vector):
        """Cosine similarity of the query with every row (-1..1)."""
        return self.vectors @ normalize(query_vector)

    def search(self, query_vector, k=10, where=None):
        """Top-k rows by cosine similarity. `where` is an optional filter on a row's record."""
        sims = self.scores(query_vector)
        if where is not None:
            mask = np.array([bool(where(r)) for r in self.records])
            sims = np.where(mask, sims, -np.inf)
        k = min(k, len(sims))
        top = np.argpartition(-sims, k - 1)[:k]           # the k best, unordered
        top = top[np.argsort(-sims[top])]                 # then sort just those
        return [(float(sims[i]), self.ids[i], self.records[i]) for i in top if np.isfinite(sims[i])]

    def get_vector(self, record_id):
        return self.vectors[self.ids.index(record_id)]

    def save(self, folder):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        np.save(folder / "vectors.npy", self.vectors)
        with open(folder / "records.jsonl", "w", encoding="utf-8") as f:
            for i, r in zip(self.ids, self.records):
                f.write(json.dumps({"id": i, **r}) + "\n")
        (folder / "manifest.json").write_text(json.dumps({
            "model": self.model, "dim": self.dim, "count": len(self),
            "dtype": "float32", "similarity": "cosine",
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, indent=2))

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        manifest = json.loads((folder / "manifest.json").read_text())
        store = cls(manifest["dim"], manifest["model"])
        store.vectors = np.load(folder / "vectors.npy")
        for line in (folder / "records.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            store.ids.append(r.pop("id"))
            store.records.append(r)
        return store

    def info(self):
        return {"model": self.model, "count": len(self), "dim": self.dim,
                "megabytes": round(self.vectors.nbytes / 1e6, 1)}
