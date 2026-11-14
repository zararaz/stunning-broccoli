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
| Vector database (one city), vector + hybrid search | Done |
| Chat app: interpret, plan, validate, write (swappable LLM) | Done |
| Production: serving bundle, server, limits, logs, tests | Done; the Docker image is not built yet |
| Resident mode and personalization eval | Planned |

## How a message flows

Every way in ends at the same pipeline in `src/engine.py`:

```
python src/chat_cli.py   ─────────────────────────────────┐
python app.py  (web page) ─┐                              ├─> Engine.handle  (src/engine.py)
server.py  POST /api/chat ─┴─> ChatService.chat ──────────┘       │
                                (src/service.py:                   ├─ 1. interpret  message -> Request     src/interpret.py
                                 limits, logins, logs)             ├─ 2. plan       Request -> Plan        src/planner.py  (uses src/search.py)
                                                                   ├─ 3. validate   open? near? repeats?   src/planner.py
                                                                   └─ 4. write      Plan -> reply          src/writer.py
```

- The terminal skips `ChatService`: it's for you alone, so it needs no limits or logins.
- Steps 1 and 4 may call an LLM (`src/llm.py`). Steps 2 and 3 are plain code.
- All configuration comes from `src/settings.py` (environment variables, or a `.env` file).

## Layout

```
src/
  settings.py       all configuration, from environment variables
  # build the data (offline, once)
  ingest.py         Yelp JSON -> data/yelp.db (businesses, categories, hours, tips, check-ins)
  profiles.py       one searchable text profile per business
  embedder.py       turns text into vectors with a free Hugging Face model
  vectordb.py       a minimal vector database: vectors.npy + records.jsonl + manifest.json
  build_vectors.py  builds the vector database for one city
  inspect_vectors.py  look inside it: info, nearest neighbors, phrase similarity
  export_bundle.py  cuts yelp.db down to a 34 MB serving bundle for one city
  # search
  db.py             opens SQLite connections
  search.py         filters (city, open, category, open at a time) + 4 ranking methods
  ivf.py            an approximate vector index (IVF) written from scratch
  # the chat pipeline
  engine.py         runs the four steps and records a trace of each
  interpret.py      step 1: message -> Request (LLM JSON, validated, rules fallback)
  planner.py        steps 2-3: Request -> Plan (itinerary, picks, weekly pick), then validate
  writer.py         step 4: Plan -> reply; the LLM writes notes only, never place facts
  llm.py            LLM backends: rules (no model), hf (local), claude; parses model JSON
  history.py        per-user pick history in data/app.db, kept apart from the Yelp data
  # ways in
  chat_cli.py       chat in the terminal
  service.py        what every web request goes through: input limits, rate limits, logins, JSON logs
app.py              the web chat page (Gradio); `python app.py` runs it on your laptop
server.py           production: the same page plus /api/chat and /health (uvicorn server:app)
tests/              standard-library tests on a made-up city
evals/              50 test queries, hand-labeling tool, retrieval metrics
bench/              scaling lab: exact search vs IVF vs FAISS
scripts/get_data.sh extracts the needed files from the Yelp download
docs/PRODUCTION.md  how it runs as a service, and what's left to do
Dockerfile, requirements-serve.txt   the production image (not built yet)
requirements.txt, requirements.lock  packages, and their exact versions
Makefile            the same build steps as below, for people who prefer make
```

## Run it

Everything is rebuilt from the raw Yelp download by scripts, so anyone can
reproduce it. Needs Python 3.10+ (the Mac's built-in `python3` is 3.9; install
3.12 from [python.org](https://www.python.org/downloads/macos/) or with
`brew install python@3.12`).

1. Download the Yelp Open Dataset ("Download JSON") from
   https://business.yelp.com/data/resources/open-dataset/
2. Set up Python (once):
   ```
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt -c requirements.lock    # exact versions from the lock file
   ```
3. Build the data (once; later runs skip work that's done):
   ```
   bash scripts/get_data.sh ~/Downloads/Yelp-JSON.zip       # extract the JSON files into data/
   python src/ingest.py                                     # data/yelp.db
   python src/profiles.py                                   # one text profile per business
   python src/search.py --build                             # keyword (BM25) index
   python src/build_vectors.py --city Philadelphia          # vector database
   ```
   The first vector build downloads the embedding model
   ([all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2))
   from Hugging Face.
4. Use it:
   ```
   python src/chat_cli.py --trace                           # chat in the terminal, no model
   python app.py                                            # web page at http://127.0.0.1:7860
   python src/search.py "quiet cafe with wifi to work" --method hybrid
   python src/inspect_vectors.py similar "Reading Terminal Market"
   python -m unittest discover -s tests                     # tests (no data needed)
   ```

`make all YELP=~/Downloads/Yelp-JSON.zip` runs steps 2 and 3 in one go.

## Chat app

Three kinds of request:

- "I'm visiting Philly on Sunday, I love art" -> a one-day itinerary
- "I live in Philly, what places should I try?" -> places to eat this week, things to do this month
- "I live in Philly, tell me a new restaurant every week" -> one new pick each time, never repeated

Design choices:

- **The LLM is a swappable part.** `rules` needs no model, `hf` runs a small open
  Hugging Face model locally, `claude` calls the Claude API. Same pipeline for all three.
- **The LLM never decides facts.** Search, opening hours, distances and variety are
  plain code. The model only turns the message into JSON and writes short notes.
- **Grounded by construction.** The writer gets place ids and returns notes keyed by id;
  names, addresses and ratings are rendered from the data, so a place can't be invented.
- **Untrusted output is validated.** Model JSON is checked field by field, with the
  rule-based parser as a fallback; a separate validator re-checks the finished plan.
- **Every step is traced**: the parsed request, the plan, the checks and timings.

Choose the backend with `--llm` (the same flag for the terminal and the web page):

```
python src/chat_cli.py --llm hf --trace       # small local model from Hugging Face
python src/chat_cli.py --llm claude --trace   # Claude API (needs a key, see below)
python app.py --llm hf
```

- `hf` downloads [Qwen2.5-0.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)
  (~1 GB) on first use and runs it on the Mac's GPU (MPS) or CPU.
- `claude` needs `ANTHROPIC_API_KEY`. Copy `.env.example` to `.env` (gitignored) and fill
  it in, or `export` it in your shell; a shell variable wins over `.env`. Without a key the
  backend refuses to start, rather than silently falling back to rules.

The trace says who did each step: `parsed_by` is `llm:<model>` or
`rules (llm failed: <error>)`; `written_by` is `llm:<model> (k/n notes)` or
`template (...)` with the reason, e.g. `llm returned no notes`.

## What the vector database is made of

`data/vectors/philadelphia/` holds three plain files:

| File | Contents |
|---|---|
| `manifest.json` | model name, row count, dimensions |
| `vectors.npy` | an N x 384 matrix of numbers, one row per business |
| `records.jsonl` | one line per row: business id, name, categories, rating, location |

Search compares the query's vector with every row (exact cosine similarity).
That is fast for a city's ~7,500 businesses; approximate indexes are for scale.

## Evaluation

```
python evals/label.py --city Philadelphia            # hand-label pooled search results
python evals/retrieval_eval.py --city Philadelphia   # P@10, R@10, nDCG@10, MRR per method
```

## Scaling lab

Exact search checks every vector, so its cost grows with the data. Approximate
indexes check only a promising part:

- **IVF** (inverted file): k-means groups the vectors into clusters; a query
  searches only the `nprobe` nearest clusters. `src/ivf.py` implements it from
  scratch in about 60 lines of numpy.
- **HNSW**: a layered graph of near neighbors that a query walks toward its
  answer. Used here through FAISS.

`python bench/scale_bench.py --store philadelphia` holds 200 business vectors
out as queries, then for growing database sizes measures each index's build
time, memory, time per query and recall@10 (how much of the exact top 10 it
finds). Results are saved to `bench/results/`. For more vectors, build every
city with `python src/build_vectors.py --city all`, then run the lab with
`--store all`.

## Production

`server.py` serves the same web page plus an HTTP API, with logins, limits and
JSON logs, from a 34 MB serving bundle (`python src/export_bundle.py`). Tests
run on every push. See [docs/PRODUCTION.md](docs/PRODUCTION.md).

The Yelp data and everything built from it stay local and are excluded by
`.gitignore`. The Docker image would contain the serving bundle, so it must not
be pushed anywhere public.
