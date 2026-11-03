# City Guide (Yelp Open Dataset)

A course project: a city guide that recommends places using retrieval over
the Yelp Open Dataset, then plans them with an LLM.

Two use cases:
- **Resident**: what to visit weekly and monthly in your own city.
- **Visitor**: a one-day itinerary for a city you're visiting.

First city: Philadelphia (the largest city in the dataset).

## Status

| Step | State |
|---|---|
| Load Yelp data into SQLite | Done |
| One text profile per business | Done |
| Filters + keyword search (BM25) | Done |
| Hand-labeled test queries and retrieval metrics | Tools done, labeling in progress |
| Vector database (one city), vector + hybrid search | Code done, run it locally |
| Itinerary planner, validator, LLM write-up | Planned |
| Resident mode and personalization eval | Planned |

## Layout

```
src/
  ingest.py      Yelp JSON -> data/yelp.db (businesses, categories, hours, tips, check-ins)
  profiles.py    one searchable text profile per business
  search.py      filters (city, open, category, open at a time) + 4 ranking methods
  vectordb.py    a minimal vector database: vectors.npy + records.jsonl + manifest.json
  embedder.py    turns text into vectors with a free Hugging Face model
  build_vectors.py  builds the vector database for one city
  inspect_vectors.py  look inside it: info, nearest neighbors, phrase similarity
  db.py          shared database helpers
evals/
  queries_philadelphia.jsonl   50 test queries
  label.py                     label pooled search results by hand
  retrieval_eval.py            P@10, R@10, nDCG@10, MRR per method
```

## Run it

Needs Python 3.10+. Keyword search needs nothing else; the vector database needs
the packages in `requirements.txt`.

0. Set up a virtual environment (once):
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

1. Download the Yelp Open Dataset and put these files in `data/`:
   `yelp_academic_dataset_business.json`, `..._checkin.json`, `..._tip.json`.
2. Build the database and search index:
   ```
   python3 src/ingest.py
   python3 src/profiles.py
   python3 src/search.py --build
   ```
3. Search:
   ```
   python3 src/search.py "quiet cafe with wifi to work" --city Philadelphia
   python3 src/search.py "late night food" --day Saturday --time 01:00
   ```
4. Build and explore the vector database (Philadelphia):
   ```
   python3 src/build_vectors.py --city Philadelphia
   python3 src/inspect_vectors.py info
   python3 src/inspect_vectors.py similar "Reading Terminal Market"
   python3 src/inspect_vectors.py compare "cozy cafe" "quiet coffee shop" "sports bar"
   python3 src/search.py "cozy spot to read" --method vector
   python3 src/search.py "cozy spot to read" --method hybrid
   ```
   The first run downloads the embedding model
   ([all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2))
   from Hugging Face.
5. Label and evaluate (vector and hybrid join automatically once the vectors exist):
   ```
   python3 evals/label.py
   python3 evals/retrieval_eval.py
   ```

## What the vector database is made of

`data/vectors/philadelphia/` holds three plain files:

| File | Contents |
|---|---|
| `manifest.json` | model name, row count, dimensions |
| `vectors.npy` | an N x 384 matrix of numbers, one row per business |
| `records.jsonl` | one line per row: business id, name, categories, rating, location |

Search compares the query's vector with every row (exact cosine similarity).
That is fast for a city's ~7,500 businesses; approximate indexes are next, for scale.

The Yelp data and everything built from it stay local and are excluded by `.gitignore`.
