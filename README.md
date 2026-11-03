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
Makefile         reproducible build: make all YELP=<archive>
requirements.txt Python packages for the vector database
scripts/
  get_data.sh    extracts the needed files from the Yelp download
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

Everything is rebuilt from the raw Yelp download by scripts, so anyone can reproduce it.
Needs Python 3.10+ and `make` (on a Mac: `xcode-select --install`).

1. Download the Yelp Open Dataset ("Download JSON") from
   https://business.yelp.com/data/resources/open-dataset/
2. Build everything, start to finish:
   ```
   make all YELP=~/Downloads/Yelp-JSON.zip
   ```
   This creates a virtual environment, installs `requirements.txt`, extracts the
   Yelp files into `data/`, builds the SQLite database, profiles and keyword index,
   then builds and inspects the Philadelphia vector database. The first run
   downloads the embedding model
   ([all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2))
   from Hugging Face. `requirements.lock` records the exact package versions used.

Or step by step:

| Command | What it does |
|---|---|
| `make setup` | virtual environment + packages |
| `make data YELP=<archive>` | extract the Yelp JSON files into `data/` |
| `make db` | SQLite database, business profiles, keyword index |
| `make vectors CITY=Philadelphia` | vector database for one city |
| `make inspect` | what's inside the vector database |
| `make label` | hand-label search results (ground truth) |
| `make eval` | score popular, keyword, vector and hybrid search |

Steps skip work that is already done. To explore by hand, activate the
environment with `source .venv/bin/activate`, then for example:

```
python src/search.py "quiet cafe with wifi to work" --method hybrid
python src/search.py "late night food" --day Saturday --time 01:00
python src/inspect_vectors.py similar "Reading Terminal Market"
python src/inspect_vectors.py compare "cozy cafe" "quiet coffee shop" "sports bar"
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
