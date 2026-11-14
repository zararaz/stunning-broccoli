"""Step 4: turn a Plan into the chat reply.

Grounding by design: the LLM never writes place names, addresses or ratings.
It returns only an intro line and a short note per place, keyed by the place's
id; the code renders everything factual from the data. A model can't invent
a restaurant it never gets to name. If its JSON is unusable, the reply is
rendered from the template alone.
"""

import json

from interpret import extract_json
from planner import plan_stops

WRITER_SYSTEM = """You write short, friendly notes for a city-guide chatbot. Reply with JSON only:
{"intro": "<one sentence>", "notes": {"<id>": "<one short sentence on why this place fits>"}}
Use only the facts given. Never mention any place that is not in the list."""


def facts(s):
    stars = f"{s['stars']}★ ({s['review_count']:,} reviews)"
    return f"{stars} · {s['address']}" if s.get("address") else stars


def line(s, notes, prefix=""):
    note = notes.get(s["business_id"]) or s["categories"]
    return f"{prefix}**{s['name']}**: {facts(s)}\n  _{note}_"


def render(plan, req, intro=None, notes=None, issues=()):
    notes = notes or {}
    if plan["mode"] == "visit":
        head = intro or f"Here's a {plan['day']} in {plan['city']}:"
        body = [line(s, notes, f"{s['time']} · {s['label']}: ") for s in plan["stops"]]
    elif plan["mode"] == "explore":
        head = intro or f"Places to try in {plan['city']}:"
        body = []
        for i, sec in enumerate(plan["sections"]):
            body.append(("\n" if i else "") + f"**{sec['title']}**")
            body += [line(s, notes, "- ") for s in sec["stops"]]
    else:
        if not plan.get("pick"):
            return "I couldn't find a new restaurant that fits. Try different preferences?"
        head = intro or f"Week {plan['week']} pick in {plan['city']}:"
        body = [line(plan["pick"], notes),
                "\nAsk again next week for a new one. I'll remember what you've tried and vary the cuisine."]
    text = head + "\n\n" + "\n".join(body)
    if issues:
        text += "\n\nHeads-up: " + "; ".join(issues) + "."
    return text


def write(plan, req, message, llm, issues):
    """Returns (reply text, how it was written)."""
    stops = plan_stops(plan)
    if llm is None or not stops:
        return render(plan, req, issues=issues), "template"
    listing = [{"id": s["business_id"], "name": s["name"], "categories": s["categories"],
                "stars": s["stars"], **({"time": s["time"]} if "time" in s else {})} for s in stops]
    # A skeleton keyed by the real ids. Small models copy the last JSON they see,
    # so the prompt shows only the shape we want back (not the parsed Request).
    skeleton = {"intro": "...", "notes": {s["business_id"]: "..." for s in stops}}
    user = (f"User asked: {message}\n"
            f"Places (use only these): {json.dumps(listing, ensure_ascii=False)}\n"
            f"Fill in this JSON, replacing every \"...\": {json.dumps(skeleton)}")
    try:
        out = extract_json(llm.chat(WRITER_SYSTEM, user, max_tokens=500))
        ids = {s["business_id"] for s in stops}
        notes = {k: str(v) for k, v in (out.get("notes") or {}).items()
                 if k in ids and str(v).strip() not in ("", "...")}             # drop unknown ids, blanks
        intro = out.get("intro")
        intro = str(intro) if intro and str(intro).strip() != "..." else None
    except Exception as e:
        return render(plan, req, issues=issues), f"template (llm failed: {type(e).__name__})"
    if not notes and intro is None:                                          # valid JSON, nothing usable
        return render(plan, req, issues=issues), "template (llm returned no notes)"
    return render(plan, req, intro, notes, issues), f"llm:{llm.name} ({len(notes)}/{len(stops)} notes)"
