"""The chat pipeline. One call per message:

    message -> interpret -> plan -> validate -> write -> reply
              (LLM or rules)  (code)  (code)  (LLM or template)

Every step's output goes into a trace, so you can see exactly what happened.
"""

import time

import history
from db import connect
from interpret import interpret
from llm import get_llm
from planner import plan_explore, plan_stops, plan_visit, plan_weekly, search_method, validate
from writer import write


class Engine:
    def __init__(self, llm_name=None, default_city="Philadelphia"):
        self.con = connect()
        self.llm = get_llm(llm_name)
        self.default_city = default_city
        self.cities = {r[0] for r in self.con.execute(
            "SELECT city FROM businesses GROUP BY city HAVING COUNT(*) >= 300")}

    def handle(self, message, user_id="demo"):
        timings, t = {}, time.perf_counter()

        def lap(name):
            nonlocal t
            now = time.perf_counter()
            timings[name] = round((now - t) * 1000)
            t = now

        req, parsed_by = interpret(message, self.llm, self.cities, self.default_city)
        lap("interpret_ms")

        method = search_method(req.city)
        if req.mode == "visit":
            plan = plan_visit(self.con, req, method)
        elif req.mode == "weekly":
            plan = plan_weekly(self.con, req, method, history.previous(user_id, req.city, ("weekly",)))
        else:
            past = {h["business_id"] for h in history.previous(user_id, req.city)}
            plan = plan_explore(self.con, req, method, past)
        lap("plan_ms")

        issues = validate(self.con, plan)
        lap("validate_ms")

        reply, written_by = write(plan, req, message, self.llm, issues)
        lap("write_ms")

        if req.mode in ("weekly", "explore") and plan_stops(plan):
            history.record(user_id, req.city, req.mode, plan_stops(plan))

        trace = {"user_id": user_id, "request": req.to_dict(), "parsed_by": parsed_by,
                 "search_method": method, "plan": plan, "issues": issues,
                 "written_by": written_by, "timings": timings}
        return reply, trace
