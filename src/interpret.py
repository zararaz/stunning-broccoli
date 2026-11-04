"""Step 1: turn a chat message into a structured Request.

The LLM is asked for JSON in a fixed schema. Its answer is validated field
by field; anything missing or invalid is filled in by the rule-based parser,
and if the LLM fails outright the rules handle the whole message.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from db import DAYS

MODES = ("visit", "explore", "weekly")
ALIASES = {"philly": "Philadelphia", "nola": "New Orleans", "st. louis": "Saint Louis",
           "st louis": "Saint Louis", "st. pete": "Saint Petersburg", "indy": "Indianapolis"}

FOOD_WORDS = {"vegan", "vegetarian", "pizza", "sushi", "ramen", "tacos", "mexican", "italian", "chinese",
              "thai", "indian", "seafood", "oysters", "steak", "steakhouse", "bbq", "barbecue", "brunch",
              "breakfast", "coffee", "dessert", "bakery", "cheesesteak", "burgers", "korean", "japanese",
              "vietnamese", "ethiopian", "mediterranean", "gluten", "halal", "noodles", "dumplings",
              "sandwiches", "pho", "ice cream", "dim sum", "cheap eats"}
ACTIVITY_WORDS = {"museum", "museums", "art", "history", "historic", "park", "parks", "garden", "music",
                  "jazz", "live music", "shopping", "market", "books", "bookstore", "comedy", "theater",
                  "sports", "kids", "family", "outdoors", "hiking", "nightlife", "cocktails", "beer",
                  "wine", "bars", "architecture", "tour", "dancing"}


@dataclass
class Request:
    mode: str = "explore"
    city: str = "Philadelphia"
    day: str = "Saturday"
    food: list = field(default_factory=list)
    activities: list = field(default_factory=list)
    budget: str | None = None          # "low", "high" or None

    def to_dict(self):
        return asdict(self)


# ---------- rule-based parser: no model, always available ----------

def find_city(text, known_cities, default):
    low = text.lower()
    for alias, city in ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", low) and city in known_cities:
            return city
    for city in sorted(known_cities, key=len, reverse=True):
        if re.search(rf"\b{re.escape(city.lower())}\b", low):
            return city
    return default


def find_day(text):
    low = text.lower()
    for d in DAYS:
        if d.lower() in low:
            return d
    if "tomorrow" in low:
        return DAYS[(date.today() + timedelta(days=1)).weekday()]
    if "today" in low or "tonight" in low:
        return DAYS[date.today().weekday()]
    if "sunday" in low:
        return "Sunday"
    return None


def find_terms(text, vocab):
    low = text.lower()
    return [w for w in sorted(vocab, key=len, reverse=True) if re.search(rf"\b{re.escape(w)}\b", low)]


def rules_interpret(message, known_cities, default_city="Philadelphia"):
    low = message.lower()
    if re.search(r"\b(every week|each week|weekly|this week|new restaurant|next week)\b", low):
        mode = "weekly"
    elif re.search(r"\b(visit|visiting|trip|in town|travel|itinerary|tourist|weekend in|day in)\b", low):
        mode = "visit"
    else:
        mode = "explore"
    budget = ("low" if re.search(r"\b(cheap|budget|inexpensive|affordable)\b", low)
              else "high" if re.search(r"\b(fancy|splurge|upscale|special occasion|fine dining)\b", low)
              else None)
    return Request(mode=mode, city=find_city(message, known_cities, default_city),
                   day=find_day(message) or "Saturday", food=find_terms(message, FOOD_WORDS),
                   activities=find_terms(message, ACTIVITY_WORDS), budget=budget)


# ---------- LLM parser: same schema, validated, rules fill the gaps ----------

def system_prompt(known_cities):
    return f"""You turn a message sent to a city-guide chatbot into JSON. Reply with JSON only.
Fields:
  "mode": "visit" if they are visiting and want a one-day itinerary,
          "explore" if they live there and want places to try,
          "weekly" if they live there and want one new restaurant for this week
  "city": one of {sorted(known_cities)}
  "day": weekday name for a visit, e.g. "Sunday", or null
  "food": list of food or drink wishes, e.g. ["vegan", "coffee"]
  "activities": list of other interests, e.g. ["art", "jazz"]
  "budget": "low", "high" or null
Example: "visiting philly on sunday, love art and cheap eats" ->
{{"mode": "visit", "city": "Philadelphia", "day": "Sunday", "food": ["cheap eats"], "activities": ["art"], "budget": "low"}}"""


def extract_json(text):
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in the model's reply")
    return json.loads(m.group(0))


def merge(raw, fallback, known_cities):
    """Keep each LLM field only if it is valid; otherwise use the rules' value."""
    req = Request(**fallback.to_dict())
    if raw.get("mode") in MODES:
        req.mode = raw["mode"]
    city = raw.get("city")
    if isinstance(city, str):
        req.city = ALIASES.get(city.lower(), city) if ALIASES.get(city.lower(), city) in known_cities else req.city
    if isinstance(raw.get("day"), str) and raw["day"].capitalize() in DAYS:
        req.day = raw["day"].capitalize()
    for key in ("food", "activities"):
        if isinstance(raw.get(key), list):
            req.__dict__[key] = [str(x).lower() for x in raw[key] if str(x).strip()][:6]
    if raw.get("budget") in ("low", "high", None):
        req.budget = raw.get("budget")
    return req


def interpret(message, llm, known_cities, default_city="Philadelphia"):
    """Returns (Request, how it was parsed)."""
    fallback = rules_interpret(message, known_cities, default_city)
    if llm is None:
        return fallback, "rules"
    try:
        raw = extract_json(llm.chat(system_prompt(known_cities), message, max_tokens=200))
        return merge(raw, fallback, known_cities), f"llm:{llm.name}"
    except Exception as e:                       # bad JSON, network error, anything
        return fallback, f"rules (llm failed: {type(e).__name__})"
