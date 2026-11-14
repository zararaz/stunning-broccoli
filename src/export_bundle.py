"""Cut the full database down to a small serving bundle for one city.

The build pipeline (ingest, profiles, vectors) runs offline on the full
785 MB database. The running app needs far less: one city's open businesses,
their categories, hours and profiles, the keyword index and the vectors.
This script copies exactly that into a self-contained folder:

    bundle/
      serve.db          SQLite: businesses, categories, hours, profiles + keyword index
      vectors/<city>/   the city's vector database
      manifest.json     what's inside: counts, sizes, SHA-256 hashes, code version

The bundle is what gets deployed. Its hashes let you check that production
serves exactly the data you tested.

Usage:
    python src/export_bundle.py --city Philadelphia            # -> bundle/
    python src/export_bundle.py --city Philadelphia --out /tmp/b
"""

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import settings
from db import read_only_uri
from embedder import city_slug
from ingest import SCHEMA, INDEXES
from profiles import SCHEMA as PROFILES_SCHEMA
from search import MIN_REVIEWS, build_index


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=settings.ROOT,
                              capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def export(city, out, min_reviews=MIN_REVIEWS):
    out = Path(out)
    if (out / "serve.db").exists():
        raise SystemExit(f"{out}/serve.db already exists: choose another --out or remove the old bundle")
    vec_src = settings.VECTORS_DIR / city_slug(city)
    if not (vec_src / "manifest.json").exists():
        raise SystemExit(f"No vectors for {city} in {vec_src}. Run: python src/build_vectors.py --city {city}")
    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "serve.db"

    # uri=True on the main connection is what lets ATTACH read a "file:...?mode=ro" URI;
    # without it SQLite treats the URI as a literal file name and fails to open it.
    con = sqlite3.connect(db_path.resolve().as_uri(), uri=True)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA + PROFILES_SCHEMA)
    con.execute("ATTACH DATABASE ? AS src", (read_only_uri(settings.DB_PATH),))
    # Same filter the app and build_vectors.py use: open, enough reviews.
    con.execute("CREATE TEMP TABLE keep AS SELECT business_id FROM src.businesses "
                "WHERE city = ? AND is_open = 1 AND review_count >= ?", (city, min_reviews))
    for table in ("businesses", "categories", "hours", "profiles"):
        con.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table} "
                    f"WHERE business_id IN (SELECT business_id FROM keep)")
    con.commit()
    con.execute("DETACH DATABASE src")
    con.executescript(INDEXES)
    build_index(con)                       # keyword (FTS5) index over the bundle's profiles
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("businesses", "categories", "hours", "profiles")}
    con.execute("VACUUM")                  # compact the file
    con.close()

    vec_dst = out / "vectors" / city_slug(city)
    shutil.copytree(vec_src, vec_dst)
    vec_manifest = json.loads((vec_dst / "manifest.json").read_text())
    if vec_manifest["count"] != counts["businesses"]:
        print(f"warning: {vec_manifest['count']:,} vectors but {counts['businesses']:,} businesses; "
              f"rebuild vectors so they match")

    manifest = {
        "city": city, "min_reviews": min_reviews, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "code_version": git_commit(), "counts": counts,
        "embedding_model": vec_manifest["model"], "vectors": vec_manifest["count"],
        "files": {str(p.relative_to(out)): {"bytes": p.stat().st_size, "sha256": sha256(p)}
                  for p in sorted(out.rglob("*")) if p.is_file()},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default=settings.CITY)
    ap.add_argument("--out", default=str(settings.ROOT / "bundle"))
    args = ap.parse_args()
    m = export(args.city, args.out)
    total = sum(f["bytes"] for f in m["files"].values())
    print(f"Bundle for {m['city']} at {args.out}  (code version {m['code_version']})")
    for name, f in m["files"].items():
        print(f"  {name:40} {f['bytes'] / 1e6:7.1f} MB  sha256 {f['sha256'][:12]}")
    print(f"  {'total':40} {total / 1e6:7.1f} MB  (full database: {settings.DB_PATH.stat().st_size / 1e6:,.0f} MB)")
    print("  " + ", ".join(f"{k} {v:,}" for k, v in m["counts"].items()))


if __name__ == "__main__":
    main()
