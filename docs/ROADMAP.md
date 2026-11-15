# Roadmap

What the project is for, how success is measured, where it stands, the
decisions behind it, and what comes next. Status as of November 2026.

## Goal

Answer a chat message like "I'm visiting Philly on Sunday, I love art and
cheap eats" with a plan a person could actually follow: places that are open
at the planned time, close together, matched to what was asked, and never
invented by a model.

## How success is measured

| Question | Measure | Where it comes from | Today |
|---|---|---|---|
| Does search find the right places? | P@10, R@10, nDCG@10, MRR for each of the 4 search methods | `evals/retrieval_eval.py` on 50 hand-labeled queries | Tools ready; labels not done |
| Is every plan valid? | validator issues per plan (closed at the planned time, hop over 5 km, repeats) | `planner.validate`, recorded in every trace | 0 issues on the test city |
| Can a model break it? | wrong or invented model output never reaches the reply | `tests/` (invalid fields, model failure, invented places) | 14/14 tests pass |
| Does approximate search scale? | recall@10 and ms per query as the store grows | `bench/scale_bench.py` | One city measured (7,310 vectors) |
| Is it cheap to serve? | serving data size, startup, requests per minute | `export_bundle.py`, `service.py` | 34 MB bundle (from 807 MB) |

## Milestones

| # | Milestone | Outcome | Status |
|---|---|---|---|
| 1 | Data foundation | Yelp JSON → SQLite, one text profile per business, rebuilt by scripts | Done |
| 2 | Keyword search | filters (city, open now, open at a time, category) + BM25 | Done |
| 3 | Vector search | embeddings, a from-scratch vector database, hybrid ranking | Done |
| 4 | Scaling lab, one city | from-scratch IVF matches FAISS recall at every `nprobe` | Done |
| 5 | Chat pipeline | interpret → plan → validate → write, with rules, local and Claude backends | Done |
| 6 | Production setup | serving bundle, API, logins, rate limits, JSON logs, tests in CI | Done, except the Docker image |
| 7 | Retrieval evaluation | hand labels for 50 queries; pick the default search method on data | In progress |
| 8 | Scaling lab at size | ~900k Yelp tips in one store; IVF list count capped to the training data | Next |
| 9 | Backend comparison | rules vs local Qwen vs Claude on parse accuracy, note quality, latency, cost | Planned |
| 10 | More cities, resident mode | other cities in the dataset; personalization measured, not assumed | Planned |

## Key decisions and trade-offs

| Decision | Why | What it costs |
|---|---|---|
| The LLM never decides facts: search, hours, distances and variety are code | Facts stay correct and testable; a weak or failing model can't produce a wrong plan | Replies are less free-form; new kinds of request need code, not just a prompt |
| Model output is untrusted: validated field by field, rules as fallback | The app works with no model at all, and a bad answer degrades one field, not the reply | Two parsers to maintain (rules and LLM) |
| Grounding by construction: the writer gets ids and returns notes keyed by id | A place can't be invented or renamed, and a test proves it | The model can't add useful facts that aren't in the data |
| The vector database and IVF index written from scratch, then benchmarked against FAISS | Understanding what an index trades (recall, speed, memory), and a check against a reference | Slower than FAISS (0.066 vs 0.022 ms per query at the same recall); FAISS stays the choice for production |
| Exact search at one city's size | ~7,500 vectors search in under 0.1 ms; an index adds complexity for no gain | Revisit at the ~900k tips store |
| SQLite and plain files, not a hosted database | Rebuildable from scripts, no service to run, easy to ship as a bundle | One writer; the history store must move to Postgres for more than one server |
| A 34 MB serving bundle cut from the 807 MB database | Small image, read-only data, hashes in a manifest, data and code roll back together | An extra export step on every data change |
| The LLM backend is fixed at startup, not chosen by visitors | Controls cost and abuse (visitors can't switch to the paid API) | Comparing backends needs separate runs |

## Risks and open questions

| Risk | Impact | Plan |
|---|---|---|
| Search quality is unmeasured until the labels exist | The default search method (hybrid) is a judgment call, not a result | Milestone 7 first; then put the eval in CI as a deploy gate |
| Labels come from one person | Bias toward one person's sense of "relevant" | Write down the grading rules; spot-check a sample twice |
| The Claude backend hasn't run with a real key | Unknown parse accuracy, latency and cost | One test run, then milestone 9 |
| The Docker image hasn't been built (Docker isn't installed here) | The production path is untested end to end | Build and run it before any hosting |
| FAISS warns that IVF has too few training points per list at 341 lists | Clusters are less reliable at small sizes | Cap the list count to the training data (milestone 8) |
| User history lives in one SQLite file | Lost or split with two servers or a disk reset | Same `history.py` interface on Postgres (see `docs/PRODUCTION.md`) |
| Yelp's data license | The data and anything built from it can't be published | Data stays gitignored; the image must not go anywhere public |

## Next steps, in order

1. Finish the 50 hand labels and compare popular, keyword, vector and hybrid search.
2. Cap IVF lists to the training data; build the ~900k tips store and rerun the scaling lab.
3. Run the Claude backend with a real key; compare the three backends.
4. Build the Docker image and run it locally; then decide on hosting.
5. Add the retrieval eval to CI once labels exist.
