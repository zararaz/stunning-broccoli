"""Tests on a tiny made-up city: no Yelp data, no models, no network, standard library only.

    python -m unittest discover -s tests -v

They pin down the behavior production depends on: the pipeline works end to
end, model output can't corrupt it, plans obey opening hours, weekly picks
never repeat, limits and logins hold, and the serving bundle is complete.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TMP = Path(tempfile.mkdtemp(prefix="city_guide_test_"))
os.environ.update({                          # before importing the app: settings are read at import
    "CITY_GUIDE_DB": str(TMP / "fixture.db"),
    "CITY_GUIDE_VECTORS": str(TMP / "vectors"),
    "CITY_GUIDE_APP_DB": str(TMP / "app.db"),
    "CITY_GUIDE_CITY": "Testville",
    "CITY_GUIDE_LLM": "rules",
    "CITY_GUIDE_USERS": "",
    "CITY_GUIDE_DEBUG_TRACE": "0",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import engine  # noqa: E402
import service  # noqa: E402
from db import connect  # noqa: E402
from ingest import INDEXES, SCHEMA  # noqa: E402
from interpret import interpret, rules_interpret  # noqa: E402
from planner import cuisines, validate  # noqa: E402
from profiles import SCHEMA as PROFILES_SCHEMA  # noqa: E402
from search import build_index, search  # noqa: E402

ALL_DAY = {d: (7 * 60, 23 * 60) for d in range(7)}
WEEKDAYS = {d: (7 * 60, 17 * 60) for d in range(5)}
LATE = {d: (17 * 60, 26 * 60) for d in range(7)}        # 5pm to 2am

# id, name, categories, hours, text, lat/lon offset
PLACES = [
    ("cafe", "Bean There", "Coffee & Tea, Cafes, Breakfast & Brunch", ALL_DAY, "coffee pastries quiet wifi", 0.000),
    ("closed_sun", "Weekday Cafe", "Coffee & Tea, Cafes", WEEKDAYS, "coffee espresso", 0.001),
    ("museum", "Testville Art Museum", "Museums, Art Museums", ALL_DAY, "art museum paintings history", 0.002),
    ("deli", "Corner Deli", "Sandwiches, Delis, Restaurants", ALL_DAY, "sandwiches lunch hoagies", 0.003),
    ("park", "River Park", "Parks", ALL_DAY, "park trail picnic garden", 0.004),
    ("italian", "Nonna's", "Italian, Restaurants", ALL_DAY, "dinner pasta romantic", 0.005),
    ("thai", "Bangkok Garden", "Thai, Restaurants", ALL_DAY, "dinner curry noodles", 0.006),
    ("mexican", "Taco Loco", "Mexican, Restaurants", ALL_DAY, "dinner tacos cheap", 0.007),
    ("japanese", "Sushi Ten", "Japanese, Sushi Bars, Restaurants", ALL_DAY, "dinner sushi", 0.008),
    ("bar", "Blue Note Bar", "Bars, Jazz & Blues, Cocktail Bars", LATE, "bar cocktails live jazz music", 0.009),
]


def build_fixture(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA + PROFILES_SCHEMA)
    for i, (bid, name, cats, hours, text, d) in enumerate(PLACES):
        con.execute("INSERT INTO businesses VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (bid, name, f"{i} Main St", "Testville", "TS", "00000", 40.0 + d, -75.0 + d,
                     4.0 + (i % 2) * 0.5, 100 + 10 * i, 1, cats, json.dumps({"RestaurantsPriceRange2": "2"})))
        con.executemany("INSERT INTO categories VALUES (?,?)", [(bid, c.strip()) for c in cats.split(",")])
        con.executemany("INSERT INTO hours VALUES (?,?,?,?)", [(bid, day, o, c) for day, (o, c) in hours.items()])
        con.execute("INSERT INTO profiles VALUES (?,?,?)", (bid, "Testville", f"{name}. {cats}. {text}"))
    con.executescript(INDEXES)
    con.row_factory = sqlite3.Row
    build_index(con)
    con.close()


class FakeLLM:
    """Stands in for a model: returns a fixed reply, or raises."""
    name = "fake"

    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def chat(self, system, user, max_tokens=500):
        if self.error:
            raise self.error
        return self.reply


def setUpModule():
    build_fixture(os.environ["CITY_GUIDE_DB"])


class Base(unittest.TestCase):
    def setUp(self):
        self.engine = engine.Engine("rules")
        self.engine.cities = {"Testville"}      # the fixture is smaller than the 300-business threshold


class TestInterpret(Base):
    def test_modes(self):
        for text, mode in [("I'm visiting Testville on Saturday", "visit"),
                           ("I live here, what should I try?", "explore"),
                           ("tell me a new restaurant every week", "weekly")]:
            self.assertEqual(rules_interpret(text, {"Testville"}, "Testville").mode, mode, text)

    def test_day_budget_and_interests(self):
        req = rules_interpret("visiting testville on sunday, cheap vegan food and jazz", {"Testville"}, "Testville")
        self.assertEqual((req.day, req.budget, req.food, req.activities), ("Sunday", "low", ["vegan"], ["jazz"]))

    def test_invalid_llm_fields_fall_back_to_rules(self):
        llm = FakeLLM('{"mode": "party", "city": "Atlantis", "day": "Funday", "food": "pizza"}')
        req, parsed_by = interpret("visiting testville on monday, love sushi", llm, {"Testville"}, "Testville")
        self.assertEqual((req.mode, req.city, req.day, req.food), ("visit", "Testville", "Monday", ["sushi"]))
        self.assertEqual(parsed_by, "llm:fake")

    def test_llm_failure_falls_back_to_rules(self):
        _, parsed_by = interpret("visiting testville", FakeLLM(error=TimeoutError()), {"Testville"}, "Testville")
        self.assertTrue(parsed_by.startswith("rules (llm failed"), parsed_by)


class TestPlanner(Base):
    def test_visit_plan_obeys_hours_and_has_no_repeats(self):
        _, trace = self.engine.handle("visiting testville on saturday, love jazz", "visitor")
        stops = trace["plan"]["stops"]
        self.assertEqual([s["slot"] for s in stops],
                         ["breakfast", "morning", "lunch", "afternoon", "dinner", "evening"])
        self.assertEqual(len({s["business_id"] for s in stops}), len(stops))
        self.assertEqual(trace["issues"], [])
        self.assertEqual(stops[-1]["business_id"], "bar")       # the only place open at 9pm

    def test_sunday_skips_the_weekday_only_cafe(self):
        _, trace = self.engine.handle("visiting testville on sunday", "visitor")
        self.assertNotIn("closed_sun", [s["business_id"] for s in trace["plan"]["stops"]])

    def test_validator_flags_a_closed_stop(self):
        plan = {"mode": "visit", "day": "Sunday", "stops": [
            {"business_id": "closed_sun", "name": "Weekday Cafe", "slot": "breakfast", "time": "09:00",
             "km_from_previous": None, "categories": "Coffee & Tea"}]}
        self.assertTrue(any("may be closed" in i for i in validate(self.engine.con, plan)))

    def test_weekly_picks_never_repeat_and_vary_cuisine(self):
        picks = [self.engine.handle("new restaurant every week please", "weekly-user")[1]["plan"]["pick"]
                 for _ in range(4)]
        self.assertEqual(len({p["business_id"] for p in picks}), 4)
        for prev, cur in zip(picks, picks[1:]):
            self.assertFalse(cuisines(prev["categories"]) & cuisines(cur["categories"]))

    def test_each_user_has_their_own_history(self):
        a = self.engine.handle("new restaurant every week", "user-a")[1]["plan"]["pick"]["business_id"]
        b = self.engine.handle("new restaurant every week", "user-b")[1]["plan"]["pick"]["business_id"]
        self.assertEqual(a, b)


class TestWriterGrounding(Base):
    def test_llm_cannot_add_or_rename_places(self):
        _, trace = self.engine.handle("new restaurant every week", "grounding")
        pid = trace["plan"]["pick"]["business_id"]
        self.engine.llm = FakeLLM(json.dumps({"intro": "Try this!", "notes": {
            pid: "Great pick.", "invented": "Fake Place is better."}}))
        reply, trace = self.engine.handle("new restaurant every week", "grounding")
        self.assertIn(trace["plan"]["pick"]["name"], reply)       # the name comes from the data
        self.assertNotIn("Fake Place", reply)                     # notes for unknown ids are dropped
        self.assertTrue(trace["written_by"].startswith("llm:fake"))


class TestService(Base):
    def test_rate_limiter_sliding_window(self):
        rl = service.RateLimiter(2, window=60)
        self.assertEqual([rl.allow("k", t) for t in (0, 1, 2)], [True, True, False])
        self.assertTrue(rl.allow("k", 61))
        self.assertTrue(rl.allow("other", 2))

    def test_basic_auth(self):
        import base64
        service.settings.USERS = {"zara": "s3cret"}
        try:
            enc = lambda s: "Basic " + base64.b64encode(s.encode()).decode()   # noqa: E731
            self.assertEqual(service.basic_auth_user(enc("zara:s3cret")), "zara")
            self.assertIsNone(service.basic_auth_user(enc("zara:wrong")))
            self.assertIsNone(service.basic_auth_user("Basic not-base64!!"))
            self.assertIsNone(service.basic_auth_user(None))
        finally:
            service.settings.USERS = {}

    def test_service_rejects_bad_input_and_answers_good_input(self):
        svc = service.ChatService(self.engine)
        for message, status in [("", 400), ("x" * (service.settings.MAX_MESSAGE_CHARS + 1), 413)]:
            with self.assertRaises(service.ChatError) as ctx:
                svc.chat(message, "u")
            self.assertEqual(ctx.exception.status, status)
        out, _ = svc.chat("i live here, what should i try", "u")
        self.assertIn("Places to try", out["reply"])
        self.assertNotIn("trace", out)                            # traces stay out of responses by default


class TestBundle(Base):
    def test_export_bundle_is_complete_and_searchable(self):
        import export_bundle
        import settings
        # A placeholder vector store in its own folder. The export only copies these files.
        # It must not go in the shared CITY_GUIDE_VECTORS folder: other tests would then
        # see "Testville has vectors" and try to load this placeholder as real vectors.
        vectors_dir = Path(tempfile.mkdtemp(prefix="vectors_", dir=TMP))
        vec = vectors_dir / "testville"
        vec.mkdir()
        (vec / "manifest.json").write_text(json.dumps({"model": "fake", "dim": 2, "count": len(PLACES)}))
        (vec / "vectors.npy").write_bytes(b"\0" * 16)
        (vec / "records.jsonl").write_text("")
        out = TMP / "bundle"
        with mock.patch.object(settings, "VECTORS_DIR", vectors_dir):
            m = export_bundle.export("Testville", out, min_reviews=10)
        self.assertEqual(m["counts"]["businesses"], len(PLACES))
        self.assertIn("vectors/testville/vectors.npy", m["files"])
        con = connect(out / "serve.db", read_only=True)
        self.assertEqual(search(con, "jazz cocktails", "Testville", k=1)[0]["business_id"], "bar")
        with self.assertRaises(sqlite3.OperationalError):            # serving connections can't write
            con.execute("DELETE FROM businesses")


if __name__ == "__main__":
    unittest.main()
