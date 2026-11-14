"""The serving core: everything a production request goes through, except HTTP.

Kept free of web-framework code so it can be tested on its own. server.py
wraps it in HTTP routes; the web UI and the API both call ChatService.chat,
so they get the same limits, logging and error handling.

Per request:  validate input -> rate limit -> engine.handle -> structured log
"""

import base64
import binascii
import json
import logging
import secrets
import sys
import threading
import time
import uuid
from collections import defaultdict, deque

import settings
from engine import Engine

log = logging.getLogger("city_guide")


def setup_logging():
    """One JSON object per line on stdout: what hosting platforms collect and search."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False


def log_event(event, **fields):
    log.info(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **fields}, default=str))


class RateLimiter:
    """Sliding window: at most `limit` requests per `window` seconds for each key
    (a user or an IP address). In memory, so it is per server process."""

    def __init__(self, limit, window=60.0):
        self.limit, self.window = limit, window
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def basic_auth_user(header):
    """The username from an HTTP Basic 'Authorization' header, if the password matches."""
    if not settings.USERS or not header or not header.lower().startswith("basic "):
        return None
    try:
        user, _, password = base64.b64decode(header[6:]).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    expected = settings.USERS.get(user)
    # compare_digest takes the same time whether or not the guess is close
    return user if expected is not None and secrets.compare_digest(password, expected) else None


def client_key(login=None, ip=None):
    """Who to rate-limit: the logged-in user, else the IP address."""
    if login:
        return f"user:{login}"
    return f"ip:{ip}" if ip else "unknown"


class ChatError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class ChatService:
    def __init__(self, llm_name=None, engine=None):
        """llm_name overrides CITY_GUIDE_LLM; engine is for tests."""
        self.engine = engine or Engine(llm_name or settings.LLM, read_only=True)
        self.limiter = RateLimiter(settings.RATE_LIMIT_PER_MINUTE)
        self.search_method = self.engine.warm()
        self.started = time.time()

    def info(self):
        return {"llm": getattr(self.engine.llm, "name", "rules"), "search": self.search_method,
                "default_city": self.engine.default_city, "cities": sorted(self.engine.cities),
                "login_required": bool(settings.USERS)}

    def chat(self, message, user_id, client_key=None):
        """Returns (response dict, full trace). Raises ChatError for a client-visible error."""
        rid = uuid.uuid4().hex[:12]
        t0 = time.perf_counter()
        message = (message or "").strip()
        problem = (ChatError(400, "Please type a message.") if not message else
                   ChatError(413, f"Messages are limited to {settings.MAX_MESSAGE_CHARS} characters.")
                   if len(message) > settings.MAX_MESSAGE_CHARS else
                   ChatError(429, "Too many messages. Try again in a minute.")
                   if not self.limiter.allow(client_key or user_id) else None)
        if problem:
            log_event("chat_rejected", request_id=rid, user=user_id, status=problem.status, chars=len(message))
            raise problem
        try:
            reply, trace = self.engine.handle(message, user_id)
        except Exception as e:
            log_event("chat_error", request_id=rid, user=user_id, error=repr(e))
            raise ChatError(500, f"Something went wrong (request {rid}).") from e
        log_event("chat", request_id=rid, user=user_id, chars=len(message),   # length only: no message text in logs
                  mode=trace["request"]["mode"], parsed_by=trace["parsed_by"], written_by=trace["written_by"],
                  search=trace["search_method"], issues=len(trace["issues"]), timings=trace["timings"],
                  total_ms=round((time.perf_counter() - t0) * 1000))
        out = {"request_id": rid, "reply": reply}
        if settings.DEBUG_TRACE:
            out["trace"] = trace
        return out, trace
