"""All configuration in one place, read from environment variables.

Same code everywhere; only the environment changes:
  laptop     defaults below (data/ folder, rules backend, no login)
  container  the Dockerfile sets paths to the serving bundle
  hosting    secrets (API key, logins) come from the host's secret settings

A .env file (gitignored, see .env.example) is read first; variables already
set in the shell or by the host win.
"""

import os
from pathlib import Path

from llm import load_env_file

load_env_file()

ROOT = Path(__file__).resolve().parent.parent


def _path(name, default):
    return Path(os.environ.get(name, default)).expanduser()


def _int(name, default):
    return int(os.environ.get(name, default))


DATA_DIR = _path("CITY_GUIDE_DATA", ROOT / "data")
DB_PATH = _path("CITY_GUIDE_DB", DATA_DIR / "yelp.db")              # Yelp data (read-only when serving)
VECTORS_DIR = _path("CITY_GUIDE_VECTORS", DATA_DIR / "vectors")     # vector databases, one folder per city
APP_DB = _path("CITY_GUIDE_APP_DB", DATA_DIR / "app.db")            # app state: users' pick history

CITY = os.environ.get("CITY_GUIDE_CITY", "Philadelphia")
LLM = os.environ.get("CITY_GUIDE_LLM", "rules")

# Serving limits
MAX_MESSAGE_CHARS = _int("CITY_GUIDE_MAX_MESSAGE_CHARS", 500)
RATE_LIMIT_PER_MINUTE = _int("CITY_GUIDE_RATE_LIMIT_PER_MINUTE", 20)

# Optional login: "alice:secret1,bob:secret2". Empty means no login (fine on a laptop only).
USERS = dict(pair.split(":", 1) for pair in os.environ.get("CITY_GUIDE_USERS", "").split(",") if ":" in pair)

# Include the full pipeline trace in API responses (handy in development, noisy in production)
DEBUG_TRACE = os.environ.get("CITY_GUIDE_DEBUG_TRACE", "0") == "1"
