# Reproduce the whole project from the raw Yelp download.
#
#   make all YELP=~/Downloads/Yelp-JSON.zip     # everything, start to finish
#
# Or step by step:
#   make setup                  Python virtual environment + packages
#   make data YELP=<archive>    extract the Yelp JSON files into data/
#   make db                     SQLite database, profiles, keyword index
#   make vectors CITY=Philadelphia   vector database for one city
#   make inspect                look inside the vector database
#   make label / make eval      hand-label results / score each search method
#   make bench                  scaling lab: exact vs IVF vs FAISS (STORE=philadelphia)
#   make vectors-all            vectors for every city (~10x more) for a bigger lab

CITY ?= Philadelphia
STORE ?= philadelphia
# Python used to create .venv the first time, e.g. make setup PYTHON=python3.12
PYTHON ?= python3
YELP ?=
PY := .venv/bin/python

.PHONY: all setup data db vectors vectors-all inspect label eval bench clean-db help

help:
	@sed -n '1,15p' Makefile

all: setup data db vectors inspect

setup: .venv/.installed
.venv/.installed: requirements.txt
	@test -x $(PY) || $(PYTHON) -c 'import sys; v = sys.version.split()[0]; ok = sys.version_info >= (3, 10); \
	  print(("Using Python " + v) if ok else ("Python 3.10+ required, but $(PYTHON) is " + v + \
	  ". Install a newer Python (see README), then run: make setup PYTHON=python3.12")); sys.exit(0 if ok else 1)'
	test -x $(PY) || $(PYTHON) -m venv .venv
	$(PY) -m pip install --upgrade pip -q
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip freeze > requirements.lock
	touch $@

data:
	bash scripts/get_data.sh "$(YELP)"

db: data/yelp.db
data/yelp.db: data/yelp_academic_dataset_business.json src/ingest.py src/profiles.py | .venv/.installed
	$(PY) src/ingest.py
	$(PY) src/profiles.py
	$(PY) src/search.py --build

vectors: setup db
	$(PY) src/build_vectors.py --city "$(CITY)"

vectors-all: setup db
	$(PY) src/build_vectors.py --city all

bench: setup
	$(PY) bench/scale_bench.py --store "$(STORE)"

inspect:
	$(PY) src/inspect_vectors.py info --city "$(CITY)"
	$(PY) src/inspect_vectors.py compare "cozy cafe" "quiet coffee shop" "sports bar" "place to watch football"

label:
	$(PY) evals/label.py --city "$(CITY)"

eval:
	$(PY) evals/retrieval_eval.py --city "$(CITY)"

clean-db:
	mkdir -p _to_delete && mv data/yelp.db data/vectors _to_delete/ 2>/dev/null || true
