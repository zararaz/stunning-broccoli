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
| Embeddings, vector search, hybrid search | Next |
| Itinerary planner, validator, LLM write-up | Planned |
| Resident mode and personalization eval | Planned |

## Layout

```
src/
  ingest.py      Yelp JSON -> data/yelp.db (businesses, categories, hours, tips, check-ins)
  profiles.py    one searchable text profile per business
  search.py      filters (city, open, category, open at a time) + ranking methods
  db.py          shared database helpers
evals/
  queries_philadelphia.jsonl   50 test queries
  label.py                     label pooled search results by hand
  retrieval_eval.py            P@10, R@10, nDCG@10, MRR per method
```

## Run it

Needs Python 3.10+. No other dependencies yet.

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
4. Label and evaluate:
   ```
   python3 evals/label.py
   python3 evals/retrieval_eval.py
   ```

The Yelp data and everything built from it stay local and are excluded by `.gitignore`.
