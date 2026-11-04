"""An IVF (inverted file) index, written from scratch with numpy.

Exact search compares the query with every vector: simple, perfectly accurate,
but the work grows with the number of vectors. IVF trades a little accuracy
for a lot of speed:

  train:  k-means groups the vectors into `n_lists` clusters ("lists")
  add:    each vector is filed under its nearest cluster center
  search: compare the query with the cluster centers only, then search
          inside the `nprobe` closest lists instead of everything

More nprobe = more lists checked = more accurate and slower.
FAISS's IndexIVFFlat works the same way, in optimized C++.
"""

import numpy as np


def top_k(scores, k):
    """Indices of the k largest scores, best first."""
    k = min(k, len(scores))
    if k <= 0:
        return np.array([], dtype=np.int64)
    idx = np.argpartition(-scores, k - 1)[:k]
    return idx[np.argsort(-scores[idx])]


def assign(x, centroids, chunk=50_000):
    """Nearest centroid (by cosine) for each row, in chunks to limit memory."""
    out = np.empty(len(x), dtype=np.int64)
    for i in range(0, len(x), chunk):
        out[i:i + chunk] = np.argmax(x[i:i + chunk] @ centroids.T, axis=1)
    return out


class IVFIndex:
    def __init__(self, n_lists, iters=10, seed=0):
        self.n_lists = n_lists
        self.iters = iters
        self.seed = seed

    def train(self, vectors):
        """Spherical k-means on a sample: centers stay unit-length, like the vectors."""
        rng = np.random.default_rng(self.seed)
        n = len(vectors)
        sample = vectors[rng.choice(n, min(n, max(50 * self.n_lists, 10_000)), replace=False)]
        centroids = sample[rng.choice(len(sample), self.n_lists, replace=False)].copy()
        for _ in range(self.iters):
            labels = assign(sample, centroids)
            sums = np.zeros_like(centroids)
            np.add.at(sums, labels, sample)
            counts = np.bincount(labels, minlength=self.n_lists)
            empty = counts == 0
            sums[empty] = sample[rng.integers(len(sample), size=int(empty.sum()))]  # re-seed empty clusters
            centroids = sums / np.maximum(np.linalg.norm(sums, axis=1, keepdims=True), 1e-12)
        self.centroids = centroids.astype(np.float32)
        return self

    def add(self, vectors):
        """File every vector under its nearest center. Vectors are stored grouped by list."""
        labels = assign(vectors, self.centroids)
        self.order = np.argsort(labels, kind="stable")          # original row ids, grouped by list
        counts = np.bincount(labels, minlength=self.n_lists)
        self.offsets = np.concatenate([[0], np.cumsum(counts)])  # list i = order[offsets[i]:offsets[i+1]]
        self.grouped = np.ascontiguousarray(vectors[self.order])
        return self

    def search(self, query, k=10, nprobe=8):
        """Return (row ids, scores) of the best k among the nprobe nearest lists."""
        lists = top_k(self.centroids @ query, nprobe)
        spans = [np.arange(self.offsets[l], self.offsets[l + 1]) for l in lists]
        idx = np.concatenate(spans) if spans else np.array([], dtype=np.int64)
        if len(idx) == 0:
            return np.array([], dtype=np.int64), np.array([], dtype=np.float32)
        scores = self.grouped[idx] @ query
        best = top_k(scores, k)
        return self.order[idx[best]], scores[best]

    def list_sizes(self):
        return np.diff(self.offsets)

    def nbytes(self):
        return self.grouped.nbytes + self.order.nbytes + self.centroids.nbytes + self.offsets.nbytes
