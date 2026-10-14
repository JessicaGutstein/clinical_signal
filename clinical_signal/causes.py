"""Part two: what may be driving a hotspot.

Outside items (public health notices, weather and air quality bulletins, local
news, and facility or network events) are kept in their own file,
external_data/outside_signals.csv. Detection never reads it. This module lines those
items up against one hotspot in two steps:

    1. Fixed rules shortlist the items. Each item is tested on place, timing,
       and diagnosis, and scored. The same data always gives the same shortlist,
       the same ranking, and the same strength labels.
    2. The shortlisted items are grouped into possible causes and each gets a
       short explanation. Claude writes it when an API key is set; fixed wording
       is used otherwise, and whenever Claude's draft fails a check.

What the AI may and may not do here:

    - It only sees items the rules shortlisted, and must cite the ones it used.
    - It may lower a strength label. It may never raise one.
    - It must write in "could" and "may". Wording that states a cause as fact
      is rejected and the fixed wording is shown instead.
    - It never confirms a cause. Only a person does that (see reviews.py).

A hotspot with nothing on its shortlist says "No outside explanation found".
"""

from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import config

SIGNALS_FILE = "outside_signals.csv"

SOURCE_TYPES = {
    "public_health": "Public health notice",
    "weather_air": "Weather and air quality",
    "news": "Local news",
    "facility_event": "Facility or network event",
}

# A plain name for each kind of cause, and the fixed sentence used when Claude is
# not writing. Every sentence is hedged: it says what could be happening, not what is.
TOPICS = {
    "facility_closure": ("A nearby hospital closed units",
                         "When a nearby hospital closes units, the patients who would have gone there may be admitted here instead."),
    "labor_action": ("A strike diverted patients here",
                     "A strike at a nearby hospital may be sending ambulances and admissions here instead."),
    "routing_change": ("A change in where ambulances take patients",
                       "A new ambulance routing rule could be moving these patients to these facilities from others, without more people falling ill."),
    "respiratory_virus": ("A respiratory virus spreading in the area",
                          "More flu-like illness in the community could be leading to more admissions for it."),
    "childhood_virus": ("A virus spreading among children",
                        "A virus known for triggering breathing problems in children could be leading to more of these admissions."),
    "air_quality": ("Poor air quality",
                    "Poor air quality may be triggering flare-ups in people with asthma or chronic lung disease."),
    "heat": ("A spell of hot weather",
             "Hot weather can lead to dehydration and extra strain on the heart and kidneys, which might add some admissions."),
    "enrollment_change": ("More members in the area, not more illness",
                          "If more people in this area joined the plan, admissions could rise simply because there are more members."),
    "service_disruption": ("A service that usually keeps patients out of hospital was interrupted",
                           "When an outpatient service is interrupted, care that is usually given without an admission may be given as an inpatient stay."),
    "care_access": ("Outpatient care became harder to reach",
                    "When clinics or pharmacies close, people may miss routine care and could end up being admitted."),
    "infection_control": ("Infection control problems at care homes nearby",
                          "Lapses in care at nearby nursing homes could be leading to more residents being admitted with infections."),
    "foodborne_outbreak": ("A local outbreak of stomach illness",
                           "A local outbreak of stomach illness may be leading to more of these admissions."),
    "outbreak": ("A local outbreak", "A local outbreak could be leading to more of these admissions."),
    "injury_trend": ("A long-running rise in injuries",
                     "A long-running rise in this kind of injury might account for part of the increase."),
    "mass_casualty": ("A single large incident", "One large incident could account for several admissions at once."),
    "service_expansion": ("The facility expanded a service", "A facility that adds capacity may admit more patients."),
}
DEFAULT_TOPIC = ("Something reported outside the plan", "An outside event could be related to these admissions.")

# --- The rules (all in days, counted from the first day of the period the hotspot covers) ---
CARRY_OVER_DAYS = 21     # an item that ended longer ago than this is too old to explain the rise
LOOK_BACK_DAYS = 60      # an item that started longer ago than this is part of the usual picture
LATE_START_DAYS = 14     # an item that started later than this came after the rise began
CLOSE_BEFORE_DAYS = 21   # "close in time": started within this many days before the rise...
STRONG, MODERATE = 6, 5  # score needed for each label; anything lower is weak
BACKGROUND_CAP = 3       # an undated trend story can never be more than weak
MAX_CAUSES = 3
MAX_ITEMS_PER_CAUSE = 3
MAX_SET_ASIDE = 8
STRENGTHS = ["weak", "moderate", "strong"]

SINGLE_FACILITY = ("pair", "facility", "facility_wide")
WHOLE_FACILITY = ("facility", "facility_wide")


# --------------------------------------------------------------------------- loading
def _split(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(";") if p.strip()]


def _day(text: str) -> date | None:
    return date.fromisoformat(text) if text else None


def load_items(data_dir: Path | None = None) -> list[dict]:
    """Read the outside items. A missing file means part two has nothing to read."""
    path = Path(data_dir or config.EXTERNAL_DIR) / SIGNALS_FILE
    if not path.exists():
        return []
    items = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            items.append({
                "id": r["item_id"], "source_type": r["source_type"], "source_name": r["source_name"],
                "published": _day(r["published"]), "starts": _day(r["starts"]), "ends": _day(r["ends"]),
                "areas": _split(r["areas"]), "facility_ids": _split(r["facility_ids"]),
                "system": r["health_system"].strip(), "topic": r["topic"],
                "direct": _split(r["diagnosis_direct"]), "indirect": _split(r["diagnosis_indirect"]),
                "population": r["population"] or "all", "level": r["level"] or "notable",
                "title": r["title"], "body": r["body"],
            })
    return items


def counts_by_source(items: list[dict]) -> dict:
    out = {"total": len(items), "by_type": []}
    for key, label in SOURCE_TYPES.items():
        out["by_type"].append({"type": key, "label": label, "count": sum(1 for i in items if i["source_type"] == key)})
    return out


# --------------------------------------------------------------------------- the three tests
def window_start(alert: dict, as_of: date) -> date:
    """First day of the period the hotspot covers."""
    period = alert.get("period", "")
    days = 14 if "two weeks" in period else 7 if period.strip() == "latest week" else config.WINDOW_DAYS
    return as_of - timedelta(days=days - 1)


def _the(area: str) -> str:
    return "the Bronx" if area == "Bronx" else area


def _plural(n: int, word: str = "day") -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _place(item: dict, alert: dict, by_id: dict) -> tuple[int, str]:
    """How well the item's place fits the hotspot's. 0 means it is somewhere else."""
    region = "All" in item["areas"]
    names = set(item["facility_ids"]) & set(alert["facility_ids"])
    if alert["kind"] in SINGLE_FACILITY:
        f = by_id[alert["facility_ids"][0]]
        if names:
            return 3, "It concerns this facility directly."
        if item["system"] and item["system"] == f.get("system"):
            return 2, f"It is about {item['system']}, the health system this facility belongs to."
        if f.get("area") in item["areas"]:
            if item["facility_ids"]:
                return 1, f"It is in {_the(f['area'])}, but it is about a different facility."
            return 2, f"It covers {_the(f['area'])}, where this facility is, but does not name the facility."
        if region:
            return 1, "It covers the whole region, so it does not point at this facility in particular."
        return 0, "It is about a different place."
    if alert.get("grouped_by") == "system":
        if item["system"] and item["system"] == alert.get("system"):
            return 3, f"It is about {item['system']}, the health system that links these facilities."
        if names == set(alert["facility_ids"]):
            return 3, "It concerns every facility in this hotspot."
        if names:
            return 2, "It concerns only some of these facilities."
        if region:
            return 1, "It covers the whole region, so it does not point at this health system in particular."
        return 0, "It is about a different place, or only part of the area these facilities cover."
    if alert["kind"] == "plan_wide":
        if region:
            return 3, "It covers the whole region, like this hotspot."
        return 1, "It covers only one part of the plan's area."
    area = alert.get("area")
    if area in item["areas"] and not item["facility_ids"]:
        return 3, f"It covers {_the(area)}, the same area as this hotspot."
    if names == set(alert["facility_ids"]):
        return 3, "It concerns every facility in this hotspot."
    if names:
        return 2, "It concerns only some of these facilities."
    if region:
        return 1, "It covers the whole region, so it does not point at this area in particular."
    return 0, "It is about a different place."


def _timing(item: dict, start: date, as_of: date) -> tuple[int, str]:
    """Whether the item could have come before the rise. 0 means the timing rules it out."""
    if item["level"] == "background":
        return 1, "It describes a long-running trend with no start date, so timing cannot be checked."
    begins, ends = item["starts"], item["ends"]
    lead = (start - begins).days  # positive: the item began before the period the hotspot covers
    if begins > as_of:
        return 0, f"It has not happened yet (it is dated {begins.strftime('%B %-d, %Y')})."
    if lead < -LATE_START_DAYS:
        return 0, f"It began {_plural(-lead)} after the rise started, so it cannot have set it off."
    if ends and (start - ends).days > CARRY_OVER_DAYS:
        return 0, f"It ended {_plural((start - ends).days)} before the rise started."
    if lead > LOOK_BACK_DAYS:
        return 0, f"It began {_plural(lead)} before the rise started, too long ago to explain a new increase."
    if lead > CLOSE_BEFORE_DAYS:
        return 1, f"It began {_plural(lead)} before the rise started, which is early but possible."
    if lead > 0:
        return 2, f"It began {_plural(lead)} before the rise started."
    if lead == 0:
        return 2, "It began on the first day of the rise."
    return 2, f"It began {_plural(-lead)} into the rise."


def _diagnosis(item: dict, alert: dict) -> tuple[int, str]:
    """Whether the item is about the kind of admission that is up. 0 means it is not."""
    everything = "All" in item["direct"]
    if alert["kind"] in WHOLE_FACILITY:
        if everything:
            return 2, "It would affect every kind of admission, and this hotspot is the whole facility."
        mine = {m["diagnosis"] for m in alert.get("members", [])}
        related = [d for d in item["direct"] + item["indirect"] if d in mine]
        if related:
            return 1, f"It relates to {related[0]}, one of the diagnosis groups that is up here, but not to the others."
        if item["direct"] and set(item["facility_ids"]) & set(alert["facility_ids"]):
            return 1, f"It relates to {item['direct'][0]} at this facility, not to every kind of admission."
        return 0, "It is not about the kinds of admission that are up here."
    dx = alert.get("diagnosis")
    if dx in item["direct"]:
        return 2, f"It is directly about {dx}."
    if everything:
        return 1, "It would raise every kind of admission, not only this diagnosis."
    if dx in item["indirect"]:
        return 1, f"It can lead to {dx} indirectly."
    return 0, f"It is not about {dx}."


def _population(item: dict, alert: dict, by_id: dict) -> tuple[int, str]:
    if item["population"] != "children" or alert["kind"] not in SINGLE_FACILITY:
        return 0, ""
    if "children" in (by_id[alert["facility_ids"][0]].get("type") or "").lower():
        return 1, "It is about children, and this is a children's hospital."
    return -2, "It is about children, and this is not a children's hospital."


def strength_of(score: int) -> str:
    return "strong" if score >= STRONG else "moderate" if score >= MODERATE else "weak"


def _public(item: dict) -> dict:
    return {
        "id": item["id"], "title": item["title"], "body": item["body"],
        "source_type": item["source_type"], "source_label": SOURCE_TYPES.get(item["source_type"], "Outside source"),
        "source_name": item["source_name"],
        "published": item["published"].isoformat(), "starts": item["starts"].isoformat(),
        "ends": item["ends"].isoformat() if item["ends"] else None,
        # The page that opens when the item is clicked. A real version would link to the source's own site.
        "url": f"/external/articles/{item['id']}.html",
    }


# --------------------------------------------------------------------------- step 1: the shortlist
def shortlist(alert: dict, facilities: list[dict], as_of: date, items: list[dict]) -> dict:
    """Apply the three tests to every outside item and group what passes into possible causes."""
    by_id = {f["id"]: f for f in facilities}
    start = window_start(alert, as_of)
    passed, set_aside = [], []
    for it in items:
        d_pts, d_text = _diagnosis(it, alert)
        if not d_pts:
            continue  # not about this kind of admission at all: not worth listing
        p_pts, p_text = _place(it, alert, by_id)
        t_pts, t_text = _timing(it, start, as_of)
        routine = it["level"] == "routine"
        failures = [(kind, text) for kind, pts, text in (("place", p_pts, p_text), ("timing", t_pts, t_text)) if not pts]
        if routine:
            failures.append(("routine", "It reports nothing unusual."))
        if failures:
            # A near miss fails exactly one test. It is worth showing, with the reason it was
            # set aside. An item somewhere else is only a near miss if it is directly about
            # this diagnosis; otherwise every closure anywhere would be listed.
            kind, text = failures[0]
            if len(failures) == 1 and (kind != "place" or d_pts == 2):
                set_aside.append({"item": _public(it), "reason": text, "_kind": kind, "_when": it["starts"]})
            continue
        pop_pts, pop_text = _population(it, alert, by_id)
        score = p_pts + t_pts + d_pts + pop_pts
        capped = it["level"] == "background" and score > BACKGROUND_CAP
        if capped:
            score = BACKGROUND_CAP
        parts = [{"test": "Place", "points": p_pts, "of": 3, "text": p_text},
                 {"test": "Timing", "points": t_pts, "of": 2, "text": t_text},
                 {"test": "Diagnosis", "points": d_pts, "of": 2, "text": d_text}]
        if pop_pts:
            parts.append({"test": "Who it affects", "points": pop_pts, "of": 1, "text": pop_text})
        if capped:
            parts.append({"test": "Limit", "points": 0, "of": 0, "text": "A trend story with no dates is never rated above weak."})
        passed.append({"topic": it["topic"], "score": score, "parts": parts, "item": _public(it), "_when": it["starts"]})

    groups: dict[str, list[dict]] = {}
    for p in passed:
        groups.setdefault(p["topic"], []).append(p)
    causes = []
    for topic, members in groups.items():
        members.sort(key=lambda m: (-m["score"], m["_when"], m["item"]["id"]))
        best = members[0]
        label, why = TOPICS.get(topic, DEFAULT_TOPIC)
        causes.append({
            "topic": topic, "label": label, "why": why, "written_by": "standard",
            "score": best["score"], "max_score": 7, "strength": strength_of(best["score"]),
            "rule_strength": strength_of(best["score"]), "parts": best["parts"],
            "n_items": len(members), "n_source_types": len({m["item"]["source_type"] for m in members}),
            "items": [m["item"] for m in members[:MAX_ITEMS_PER_CAUSE]],
            "_first": min(m["_when"] for m in members),
        })
    causes.sort(key=lambda c: (-c["score"], -c["n_items"], c["_first"], c["topic"]))
    for extra in causes[MAX_CAUSES:]:
        set_aside.append({"item": extra["items"][0], "reason": f"It fits, but {MAX_CAUSES} other possible causes fit better.",
                          "_kind": "ranked", "_when": date.fromisoformat(extra["items"][0]["starts"])})
    causes = causes[:MAX_CAUSES]
    for rank, c in enumerate(causes, start=1):
        c["rank"] = rank
        del c["_first"]
    # Most telling first: lower-ranked fits, then right place but wrong time, then
    # routine bulletins, then the right diagnosis somewhere else. Newest first within each.
    order = {"ranked": 0, "timing": 1, "routine": 2, "place": 3}
    set_aside.sort(key=lambda s: (order[s["_kind"]], -s["_when"].toordinal(), s["item"]["id"]))
    # Weekly bulletins repeat. Show the newest of each kind and say how many more there were.
    shown, routine_seen = [], {}
    for s in set_aside:
        if s["_kind"] != "routine":
            shown.append(s)
            continue
        key = (s["item"]["source_type"], s["item"]["title"].split(":")[0])
        if key in routine_seen:
            routine_seen[key]["_more"] += 1
        else:
            s["_more"] = 0
            routine_seen[key] = s
            shown.append(s)
    for s in routine_seen.values():
        if s["_more"]:
            s["reason"] = f"It reports nothing unusual, and neither do {_plural(s['_more'], 'earlier bulletin')} like it."
    set_aside = shown
    n_set_aside = len(set_aside)
    return {
        "causes": causes,
        "set_aside": [{"item": s["item"], "reason": s["reason"]} for s in set_aside[:MAX_SET_ASIDE]],
        "n_set_aside": n_set_aside,
        "n_items_read": len(items),
        "rise_started": start.isoformat(),
    }


# --------------------------------------------------------------------------- step 2: the explanation
DEFINITE = re.compile(
    r"\b(is caused by|was caused by|are caused by|the cause is|the cause of|caused the|is causing|are causing|is driving|"
    r"are driving|is due to|are due to|because of|as a result of|proves?|proved|confirms?|confirmed|certainly|definitely|"
    r"clearly|undoubtedly|without doubt|explains the|is responsible|are responsible|led to the|is why)\b",
    re.IGNORECASE,
)
HEDGE = re.compile(r"\b(may|might|could|can|possibl[ey]|perhaps|appears? to|if)\b", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
MAX_WHY_CHARS, MAX_WHY_SENTENCES, MAX_LABEL_CHARS = 380, 2, 90

SYSTEM_PROMPT = """You help a health plan analyst judge what may be driving a hotspot of inpatient admissions.
The admissions are the plan's own members, admitted to outside facilities the plan contracts with.

You will receive JSON with one hotspot and a shortlist of possible causes. Fixed rules built the shortlist
from outside items (public health notices, weather and air quality bulletins, local news, facility events).
Each possible cause has a topic, the strength the rules gave it, and the items behind it.

Read the items and reply with JSON only, in this shape:
{"causes": [{"topic": "<topic from the shortlist>", "label": "<plain name for the possible cause, a few words>",
  "why": "<one or two plain sentences on how this could lead to these admissions>",
  "cites": ["<item id>", ...], "strength": "strong" | "moderate" | "weak"}]}

Rules:
- Include every topic from the shortlist once, and no others.
- "cites" must list the ids of the items you relied on, taken only from that topic's items.
- You may keep the strength the rules gave, or lower it if the items do not really support the idea. Never raise it.
- Write in "could", "may" or "might". You are suggesting, not concluding. Never state a cause as fact.
- Use only numbers that appear in the items. Do not give admission counts or costs.
- No advice and no recommendations. A person will confirm or reject each possible cause."""


def facts(alert: dict, result: dict) -> dict:
    """What Claude is given: the hotspot in words, and only the shortlisted items."""
    return {
        "hotspot": {"what": alert["title"], "where": alert["subtitle"], "period": alert["period"],
                    "rise_started": result["rise_started"], "kind": alert["kind"]},
        "possible_causes": [{
            "topic": c["topic"], "rule_strength": c["rule_strength"],
            "how_it_fits": [p["text"] for p in c["parts"]],
            "items": [{"id": i["id"], "source": i["source_label"], "title": i["title"], "text": i["body"],
                       "starts": i["starts"], "ends": i["ends"]} for i in c["items"]],
        } for c in result["causes"]],
    }


def check_cause(draft: dict, cause: dict, given: dict) -> str | None:
    """The reason one of Claude's possible causes must be rejected, or None if it is fine."""
    label, why = str(draft.get("label", "")).strip(), str(draft.get("why", "")).strip()
    if not label or not why:
        return "it left the name or the explanation empty"
    if len(label) > MAX_LABEL_CHARS or len(why) > MAX_WHY_CHARS or len(SENTENCE_END.findall(why)) > MAX_WHY_SENTENCES:
        return "it was longer than one or two plain sentences"
    cites = draft.get("cites")
    allowed_ids = {i["id"] for i in cause["items"]}
    if not isinstance(cites, list) or not cites or not set(cites) <= allowed_ids:
        return "it did not cite the items it was given"
    strength = draft.get("strength")
    if strength not in STRENGTHS:
        return "it gave no strength"
    if STRENGTHS.index(strength) > STRENGTHS.index(cause["rule_strength"]):
        return "it rated the cause higher than the rules allow"
    text = f"{label} {why}"
    definite = DEFINITE.search(text)
    if definite:
        return f"it stated a cause as fact (\"{definite.group(0)}\")"
    if not HEDGE.search(why):
        return "it did not say \"could\" or \"may\""
    allowed_numbers = {m.replace(",", "") for m in NUMBER.findall(json.dumps(given))}
    for token in NUMBER.findall(text):
        if token.replace(",", "").rstrip(".") not in allowed_numbers:
            return f"it used a number that is not in the items ({token})"
    return None


def _parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def ai_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def explain(alert: dict, result: dict) -> dict:
    """Add a plain name and explanation to each possible cause, and say honestly who wrote them."""
    causes = result["causes"]
    if not causes:
        result["note"] = "Fixed rules only. Nothing passed the rules, so there was nothing for AI to read."
        result["writer"] = "rules"
        return result
    if not ai_enabled():
        result["note"] = ("The shortlist and the strength labels come from fixed rules. The explanations are standard wording. "
                          "Set an Anthropic API key to have Claude read the items and write them.")
        result["writer"] = "standard"
        return result
    try:
        import anthropic

        given = facts(alert, result)
        reply = anthropic.Anthropic().messages.create(
            model=os.environ.get("CLINICAL_SIGNAL_CAUSE_MODEL", config.CAUSE_MODEL),
            max_tokens=900,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(given, indent=2)}],
        )
        text = "\n".join(b.text for b in reply.content if getattr(b, "type", "") == "text")
        drafts = {d.get("topic"): d for d in _parse(text).get("causes", []) if isinstance(d, dict)}
    except Exception as exc:  # no network, bad key, a reply that is not JSON: the tab still works
        result["note"] = (f"Claude's reading could not be used ({type(exc).__name__}), so the explanations are standard wording. "
                          "The shortlist and the strength labels come from fixed rules.")
        result["writer"] = "standard"
        return result

    rejected = []
    for c in causes:
        draft = drafts.get(c["topic"])
        problem = "it left this possible cause out" if draft is None else check_cause(draft, c, given)
        if problem:
            rejected.append(f"{c['label']}: {problem}")
            continue
        c["label"], c["why"], c["written_by"] = draft["label"].strip(), draft["why"].strip(), "claude"
        c["cited"] = list(draft["cites"])
        if draft["strength"] != c["rule_strength"]:
            c["strength"] = draft["strength"]
            c["lowered_by_ai"] = True
    # Claude may only lower a label, so the order can only change by a cause moving down.
    causes.sort(key=lambda c: (-STRENGTHS.index(c["strength"]), c["rank"]))
    for rank, c in enumerate(causes, start=1):
        c["rank"] = rank
    written = sum(1 for c in causes if c["written_by"] == "claude")
    result["writer"] = "claude" if written else "standard"
    result["note"] = ("Fixed rules chose the shortlist and set the strength labels. "
                      + (f"Claude read the shortlisted items and wrote {written} of {len(causes)} explanations, each checked before it was shown."
                         if written else "Claude's explanations were all rejected, so standard wording is shown.")
                      + (f" Rejected and replaced with standard wording: {'; '.join(rejected)}." if rejected else ""))
    return result


def find(alert: dict, facilities: list[dict], as_of: date, items: list[dict]) -> dict:
    """Everything the "What's driving it" tab needs for one hotspot, before review decisions are added."""
    return explain(alert, shortlist(alert, facilities, as_of, items))
