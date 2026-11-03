"""Turns text into vectors with a free model from Hugging Face.

The model downloads automatically the first time (about 90 MB) and is cached.
Heavy libraries are imported only when needed, so keyword search still runs
without them.
"""

from db import ROOT

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"   # 384 dimensions, small and fast
VECTORS_DIR = ROOT / "data" / "vectors"

_models = {}
_stores = {}


def city_slug(city):
    return city.lower().replace(" ", "_")


def store_path(city):
    return VECTORS_DIR / city_slug(city)


def has_vectors(city):
    return (store_path(city) / "manifest.json").exists()


def load_model(name=DEFAULT_MODEL):
    if name not in _models:
        import torch
        from sentence_transformers import SentenceTransformer
        device = "mps" if torch.backends.mps.is_available() else "cpu"   # mps = Apple silicon GPU
        _models[name] = SentenceTransformer(name, device=device)
    return _models[name]


def embed(texts, model_name=DEFAULT_MODEL, batch_size=64, progress=False):
    model = load_model(model_name)
    return model.encode(texts, batch_size=batch_size, show_progress_bar=progress,
                        normalize_embeddings=True, convert_to_numpy=True)


def load_store(city):
    if city not in _stores:
        from vectordb import VectorStore
        _stores[city] = VectorStore.load(store_path(city))
    return _stores[city]


def vector_scores(city, query):
    """{business_id: cosine similarity} for every business in the city's vector store."""
    store = load_store(city)
    q = embed([query], store.model)[0]
    return dict(zip(store.ids, store.scores(q).tolist()))
