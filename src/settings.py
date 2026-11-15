"""All configuration in one place, read from environment variables.

Every other file reads its settings from here; none reads os.environ itself.
(Exception: the Anthropic SDK reads ANTHROPIC_API_KEY on its own.)

Same code everywhere; only the environment changes:
  laptop     defaults below (data/ folder, rules backend, no login)
  container  the Dockerfile sets paths to the serving bundle
  hosting    secrets (API key, logins) come from the host's secret settings

A .env file (gitignored, see .env.example) is read first; variables already
set in the shell or by the host win. Standard library only.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env_file(path=ROOT / ".env"):
    """Read KEY=value lines from .env into os.environ, without overriding
    variables that are already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_env_file()


def _path(name, default):
    return Path(os.environ.get(name, default)).expanduser()


def _int(name, default):
    return int(os.environ.get(name, default))


# Data
DATA_DIR = _path("CITY_GUIDE_DATA", ROOT / "data")                  # Yelp JSON files and everything built from them
DB_PATH = _path("CITY_GUIDE_DB", DATA_DIR / "yelp.db")              # Yelp data (read-only when serving)
VECTORS_DIR = _path("CITY_GUIDE_VECTORS", DATA_DIR / "vectors")     # vector databases, one folder per city
APP_DB = _path("CITY_GUIDE_APP_DB", DATA_DIR / "app.db")            # app state: users' pick history
CITY = os.environ.get("CITY_GUIDE_CITY", "Philadelphia")

# LLM backend: rules (no model), hf (local Hugging Face model) or claude (Claude API)
LLM = os.environ.get("CITY_GUIDE_LLM", "rules")
HF_MODEL = os.environ.get("CITY_GUIDE_HF_MODEL", "Qwen/Qwen2.5-0.5B-Instruct")   # ~1 GB, fits a laptop
CLAUDE_MODEL = os.environ.get("CITY_GUIDE_CLAUDE_MODEL", "claude-haiku-5-5")

# Serving limits
MAX_MESSAGE_CHARS = _int("CITY_GUIDE_MAX_MESSAGE_CHARS", 500)
RATE_LIMIT_PER_MINUTE = _int("CITY_GUIDE_RATE_LIMIT_PER_MINUTE", 20)

# Optional login: "alice:secret1,bob:secret2". Empty means no login (fine on a laptop only).
USERS = dict(pair.split(":", 1) for pair in os.environ.get("CITY_GUIDE_USERS", "").split(",") if ":" in pair)

# Include the full pipeline trace in API responses (handy in development, noisy in production)
DEBUG_TRACE = os.environ.get("CITY_GUIDE_DEBUG_TRACE", "0") == "1"
