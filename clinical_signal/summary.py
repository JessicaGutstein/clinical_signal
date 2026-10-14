"""Writes the short plain-language summary at the top of a hotspot's Detected tab.

This is the only place AI is used. Detection never depends on it.

Two writers are available:

    Claude     used when the ANTHROPIC_API_KEY environment variable is set
    standard   fixed wording filled in from the alert; always available

Either way the summary is one or two sentences for a reader with no background in
detection: what is higher than usual, where, and over what period. It never says
why. It also carries no figures: the amount above expected, the cost, and the
checks each have their own place on the screen, and nothing is shown twice. The
facts handed to Claude leave those figures out, so a draft that brings one in
fails the number check.

Anything Claude writes is checked before it is shown: if it is too long, contains
a number that is not in its facts, or uses wording that points at a cause, it is
discarded and the standard wording is used instead.
"""

from __future__ import annotations

import json
import os
import re

import config

CAUSAL = re.compile(
    r"\b(because|due to|caused|causing|cause of|as a result|result of|owing to|"
    r"attribut\w+|driven by|explained by|thanks to|stems? from|linked to|likely|suggests?)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
MAX_SENTENCES, MAX_CHARS = 3, 420

SYSTEM_PROMPT = """You write short summaries of inpatient admission hotspots for a health plan, for readers who are new to the topic.
The admissions are the plan's own members, admitted to outside facilities the plan contracts with.

You will receive the facts for one hotspot as JSON. Write one or two plain sentences
saying what is higher than usual, where, and over what period. Use everyday words.

Rules:
- Do not give any counts, percentages, or dollar amounts. The screen shows those elsewhere.
  The only numbers you may use are ones that appear in the facts, exactly as given.
- Describe what and where. Never say or hint at why it is happening.
- No bullet points, no headings, no advice, and no recommendations."""


def facts(alert: dict, facility: dict | None = None) -> dict:
    """What a summary is allowed to use. Counts, cost, and the checks tally are
    left out on purpose, so the summary cannot repeat them."""
    out = {
        "kind": alert["kind"],
        "what": alert["title"],
        "where": alert["subtitle"],
        "period": alert["period"],
        "potentially_avoidable": bool(alert.get("avoidable")),
        "window_days": config.WINDOW_DAYS,
    }
    if facility:
        out["facility_type"] = facility.get("type")
        out["area"] = facility.get("area")
        if facility.get("system") and facility["system"] != config.INDEPENDENT:
            out["health_system"] = facility["system"]
    elif alert.get("area"):
        out["area"] = alert["area"]
    if alert.get("system"):
        out["health_system"] = alert["system"]
    if alert["kind"] == "facility":
        out["groups_elevated"] = len(alert["members"])
    if alert["kind"] in ("wave", "plan_wide"):
        out["facilities"] = [m["short_name"] for m in alert["members"]]
    return out


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (", and " if len(items) > 2 else " and ") + items[-1]


def _place(f: dict) -> str:
    """'Borough Park Medical Center, an acute care hospital in Brooklyn, part of ...'."""
    kind = (f.get("facility_type") or "").strip()
    if not kind or not f.get("area"):
        return f["where"]
    kind = kind[0].lower() + kind[1:]
    article = "an" if kind[0] in "aeiou" else "a"
    system = f", part of {f['health_system']}" if f.get("health_system") else ""
    return f"{f['where']}, {article} {kind} in {f['area']}{system}"


def standard_summary(alert: dict, facility: dict | None = None) -> str:
    """Fixed wording, filled in from the alert. Every count here is of the plan's own
    members, so the wording says "member admissions"."""
    f = facts(alert, facility)
    period = f"the {f['period']}"
    what = f["what"]
    if what[1:2].islower():  # "Heart failure" -> "heart failure", but "COPD" and "COVID-19" stay as they are
        what = what[0].lower() + what[1:]
    if f.get("area") == "Bronx":
        f["area"] = "the Bronx"
    f["where"] = re.sub(r"\bin Bronx\b", "in the Bronx", f["where"])
    if f["kind"] == "pair":
        text = f"More member admissions for {what} than usual at {_place(f)}, over {period}."
    elif f["kind"] == "wave" and f.get("health_system") and not f.get("area"):
        text = (f"More member admissions for {what} than usual at {len(f['facilities'])} facilities of {f['health_system']}, "
                f"over {period}: {_join(f['facilities'])}. They are in different areas, so the health system is what links them.")
    elif f["kind"] == "wave":
        text = (f"More member admissions for {what} than usual at {f['where'].replace(' in ', ' close together in ')}, "
                f"over {period}: {_join(f['facilities'])}.")
    elif f["kind"] == "plan_wide":
        text = (f"More member admissions for {what} than usual across the whole plan over {period}. "
                f"No single facility stands out; the largest increases are at {_join(f['facilities'])}.")
    elif f["kind"] == "facility":
        text = (f"More member admissions than usual at {_place(f)}, over {period}. "
                f"The increase shows up in {f['groups_elevated']} different diagnosis groups, not just one.")
    else:  # facility_wide
        text = (f"More member admissions than usual at {_place(f)}, over {period}. "
                f"The increase is spread thinly, so no single diagnosis group stands out.")
    if f["potentially_avoidable"]:
        text += " This diagnosis is on the list of admissions that good outpatient care can often prevent."
    return text


def check(text: str, alert_facts: dict) -> str | None:
    """Return the reason a model-written summary must be rejected, or None if it is fine."""
    if not text.strip():
        return "it was empty"
    allowed = {m.replace(",", "") for m in NUMBER.findall(json.dumps(alert_facts))}
    for token in NUMBER.findall(text):
        if token.replace(",", "").rstrip(".") not in allowed:
            return f"it used a number that is not in its facts ({token})"
    cause = CAUSAL.search(text)
    if cause:
        return f"it used wording that points at a cause (\"{cause.group(0)}\")"
    if len(text) > MAX_CHARS or len(SENTENCE_END.findall(text)) > MAX_SENTENCES or "\n-" in text or text.lstrip().startswith(("-", "*", "•")):
        return "it was not one or two plain sentences"
    return None


def ai_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def write_summary(alert: dict, facility: dict | None = None) -> dict:
    """The summary plus an honest note on who wrote it."""
    fallback = standard_summary(alert, facility)

    def standard(note: str) -> dict:
        return {"text": fallback, "source": "standard", "note": note}

    if not ai_enabled():
        return standard("Standard wording. Set an Anthropic API key to have Claude write this summary.")
    try:
        import anthropic

        alert_facts = facts(alert, facility)
        reply = anthropic.Anthropic().messages.create(
            model=os.environ.get("CLINICAL_SIGNAL_MODEL", config.SUMMARY_MODEL),
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(alert_facts, indent=2)}],
        )
        text = "\n".join(b.text for b in reply.content if getattr(b, "type", "") == "text").strip()
        problem = check(text, alert_facts)
        if problem:
            return standard(f"Claude's draft was rejected because {problem}, so the standard wording is shown.")
        return {"text": text, "source": "claude", "note": "Written by Claude and checked before it was shown."}
    except Exception as exc:  # no network, bad key, missing package: the alert still works
        return standard(f"Claude could not be reached ({type(exc).__name__}), so the standard wording is shown.")
