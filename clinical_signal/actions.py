"""Part three: who can act.

For each cause a person has confirmed in part two, this module names an owner
and a recommendation. Both come from one file, data/action_mapping.csv: the
mapping from a kind of cause (and, where it matters, the facility's network
status) to the business area that owns it and that area's standard
recommendation.

In a real plan each business area would write and approve its own entries. Here
every entry is a draft written for the prototype, and the screen says so.

Three steps, in order:

1. Rules. `recommend` looks the confirmed cause up in the mapping. The same cause
   and the same facility labels always give the same owner and the same entry.
   No confirmed cause means no recommendation, only "Needs analyst review".
2. AI. For an entry that recommends an action, Claude rewrites the standard
   wording for this hotspot and drafts a hand-off message. `check_draft` rejects
   anything with a number it was not given, a promise that the action will work,
   or a different owner. Without an API key, or when a draft is rejected, the
   standard wording and a standard message are used. Claude never turns a
   "monitor" entry into an action: those always use the standard wording.
3. People. An analyst accepts, edits, or declines. On accept the hand-off message
   is shown for the analyst to copy and send; the app sends nothing. The owner's
   answer is then recorded. `Decisions` keeps all of it in data/action_decisions.json.
"""

from __future__ import annotations

import csv
import json
import os
import re
import threading
from datetime import date, datetime
from pathlib import Path

import config

MAPPING_FILE = "action_mapping.csv"
DECISIONS_FILE = "action_decisions.json"

# The business areas the brief names, plus the plan team that works with a facility
# when only the facility can make the change. A hospital is never an owner.
OWNERS = ("Care management", "Network and contracting", "Network and contracting, with the facility",
          "Clinical operations", "Medical cost and trend", "Clinical analytics")
REVIEW_OWNER, REVIEW_CONTACT = "Clinical analytics", "Clinical analytics analyst"

# What kind of answer an entry gives. Only the first asks anyone to do something.
OUTCOMES = {
    "action": "Recommended action",
    "monitor": "No action recommended: monitor",
    "adjust": "No clinical action: adjust what is expected",
}
# A condition narrows an entry to hotspots where every facility has this network status.
CONDITIONS = {"any": None, "in-network": "In-network", "value-based": "In-network, value-based contract",
              "out-of-network": "Out-of-network"}

DECISIONS = ("accepted", "declined")
ANSWERS = ("agreed", "declined")
MAX_TEXT, MAX_NOTE, MAX_NAME, MAX_SUBJECT, MAX_BODY = 600, 500, 60, 200, 2500
WEAK_CAUTION = ("The evidence for this cause was rated weak. Treat this as something to look into, "
                "not something to act on yet.")


# --------------------------------------------------------------------------- the mapping
def load_mapping(data_dir: Path | None = None) -> list[dict]:
    """Read the mapping. A missing file means part three can only say 'Needs analyst review'."""
    path = Path(data_dir or config.DATA_DIR) / MAPPING_FILE
    if not path.exists():
        return []
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for n, r in enumerate(csv.DictReader(f), start=2):
            row = {k: (v or "").strip() for k, v in r.items()}
            row["condition"] = row["condition"] or "any"
            for field, allowed in (("owner", OWNERS), ("outcome", OUTCOMES), ("condition", CONDITIONS)):
                if row[field] not in allowed:
                    raise ValueError(f"{MAPPING_FILE} line {n}: unknown {field} '{row[field]}'.")
            if not row["topic"] or not row["recommendation"] or not row["contact_role"]:
                raise ValueError(f"{MAPPING_FILE} line {n}: topic, recommendation and contact_role are required.")
            row["also_consider"] = [p.strip() for p in row["also_consider"].split("|") if p.strip()]
            row["status"] = row["status"] or "Draft"
            rows.append(row)
    return rows


def summary(mapping: list[dict]) -> dict:
    """What the plan-level tab says about the mapping."""
    owners: dict[str, int] = {}
    for r in mapping:
        owners[r["owner"]] = owners.get(r["owner"], 0) + 1
    return {"entries": len(mapping), "approved": sum(1 for r in mapping if r["status"].lower() == "approved"),
            "kinds_of_cause": len({r["topic"] for r in mapping}),
            "owners": [{"owner": o, "count": owners[o]} for o in OWNERS if o in owners]}


def lookup(mapping: list[dict], topic: str, networks: set[str]) -> tuple[dict | None, str]:
    """The entry for this kind of cause. An entry with a condition wins when every facility meets it."""
    rows = [r for r in mapping if r["topic"] == topic]
    for r in rows:
        if r["condition"] != "any" and networks == {CONDITIONS[r["condition"]]}:
            return r, r["condition"]
    for r in rows:
        if r["condition"] == "any":
            return r, "any"
    return None, ""


def _money_free(n) -> str:
    return f"{int(round(n)):,}"


def recommend(alert: dict, facilities: list[dict], found: dict, mapping: list[dict]) -> dict:
    """Owner and recommendation for each confirmed cause. `found` is a part-two result with decisions attached."""
    by_id = {f["id"]: f for f in facilities}
    here = [by_id[i] for i in alert["facility_ids"] if i in by_id]
    networks = {f["network"] for f in here}
    confirmed = [c for c in found.get("causes", []) if (c.get("review") or {}).get("decision") == "confirmed"]
    hotspot = {"title": alert["title"], "where": alert["subtitle"], "period": alert["period"],
               "reported": alert["display"]["observed"], "expected": alert["display"]["expected"],
               "excess": alert["display"]["excess"], "n_facilities": len(here),
               "network": sorted(networks)}
    out = {"hotspot": hotspot, "recommendations": [], "default": None}
    if not confirmed:
        waiting = len(found.get("causes", []))
        out["default"] = {
            "owner": REVIEW_OWNER, "contact_role": REVIEW_CONTACT, "n_possible": waiting,
            "text": (f"{waiting} possible {'cause is' if waiting == 1 else 'causes are'} waiting for a person to confirm or reject "
                     "on the “What’s driving it” tab." if waiting else
                     "No outside explanation was found, so a person needs to look at this hotspot before anyone is asked to act."),
        }
        return out
    for c in confirmed:
        row, matched = lookup(mapping, c["topic"], networks)
        cause = {"topic": c["topic"], "label": c["label"], "strength": c["strength"], "why": c["why"],
                 "confirmed_by": c["review"]["reviewer"], "confirmed_at": c["review"]["at"], "note": c["review"].get("note", ""),
                 "items": [{"id": i["id"], "title": i["title"], "url": i.get("url"), "source_label": i["source_label"]} for i in c["items"]]}
        rec = {"topic": c["topic"], "cause": cause, "caution": WEAK_CAUTION if c["strength"] == "weak" else None,
               "written_by": "standard", "message": None}
        if row is None:
            rec.update(outcome="unmapped", outcome_label="Needs analyst review", owner=REVIEW_OWNER, contact_role=REVIEW_CONTACT,
                       standard="The mapping has no entry for this kind of cause yet, so there is no standard recommendation. A person needs to decide what to do.",
                       why_owner="No business area has been assigned this kind of cause. Until one is, the analyst who confirmed it keeps it.",
                       also_consider=[], status=None, last_reviewed="", source=None, condition="")
        else:
            why = row["why_owner"]
            if matched != "any":
                why += (f" This entry applies because {'this facility is' if len(here) == 1 else 'every facility here is'} "
                        f"{CONDITIONS[matched].lower()}.")
            rec.update(outcome=row["outcome"], outcome_label=OUTCOMES[row["outcome"]], owner=row["owner"], contact_role=row["contact_role"],
                       standard=row["recommendation"], why_owner=why, also_consider=row["also_consider"], status=row["status"],
                       last_reviewed=row["last_reviewed"], condition=matched,
                       source={"title": row["source_title"], "url": row["source_url"]} if row["source_url"] else None)
        rec["text"] = rec["standard"]
        out["recommendations"].append(rec)
    return out


# --------------------------------------------------------------------------- the hand-off message
def _when(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def standard_message(hotspot: dict, rec: dict, text: str) -> dict:
    """The fixed hand-off message. Used when Claude is off, when its draft is rejected, or when the analyst edited the text."""
    c = rec["cause"]
    asks = rec["outcome"] == "action"
    items = "\n".join(f"- {i['title']} ({i['source_label']})" for i in c["items"])
    lines = [
        f"Hotspot: {hotspot['title']}, {hotspot['where']}. {_money_free(hotspot['reported'])} member admissions were reported in the "
        f"{hotspot['period']}, against about {_money_free(hotspot['expected'])} expected.",
        f"Confirmed cause: {c['label']}. Confirmed by {c['confirmed_by']} on {_when(c['confirmed_at'])}."
        + (f" The evidence was rated {c['strength']}." if c["strength"] != "strong" else ""),
        f"Evidence:\n{items}",
        f"{'Recommended action' if asks else 'Recommendation'}: {text}",
    ]
    if rec.get("status") and rec["status"].lower() != "approved":
        lines.append(f"This is a draft entry in the mapping. {rec['owner'].split(',')[0]} has not yet approved it as its standard recommendation.")
    if rec.get("source"):
        lines.append(f"Background for the draft: {rec['source']['title']}, {rec['source']['url']}")
    lines.append("Please reply to say whether you agree this is the right action, or what you would do instead." if asks
                 else "No action is asked of you now. Please reply if you see this differently.")
    return {"to": f"{rec['contact_role']}, {rec['owner']}",
            "subject": f"{hotspot['title']}, {hotspot['where']}: {'action requested' if asks else 'for your awareness'}"[:MAX_SUBJECT],
            "body": "\n\n".join(lines)}


# --------------------------------------------------------------------------- AI: tailor and draft
PROMISE = re.compile(r"\b(will (reduce|prevent|fix|stop|lower|solve|cut|end)|proven|guarantee[ds]?|is certain to|ensures? that)\b", re.IGNORECASE)
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
SENTENCE_END = re.compile(r"[.!?](?:\s|$)")
MAX_AI_TEXT, MAX_AI_SENTENCES, MAX_AI_BODY = 340, 2, 1200

SYSTEM_PROMPT = """You help a health plan analyst hand a hotspot of inpatient admissions to the team that can act on it.
The admissions are the plan's own members, admitted to outside facilities the plan contracts with.

You will receive JSON with one hotspot, the cause a person has confirmed, and the owning team's standard
recommendation for that kind of cause. Fixed rules chose the owner and the recommendation. You do not choose either.

Reply with JSON only, in this shape:
{"recommendation": "<the standard recommendation reworded for this hotspot, one or two plain sentences>",
 "subject": "<subject line for the hand-off message>",
 "body": "<the hand-off message: what was found, the confirmed cause, the recommended action, and one clear ask>"}

Rules:
- Keep the action the same as the standard recommendation. You may name the place, the diagnosis and the confirmed cause. Do not add a new action.
- Use only facts and numbers that appear in the JSON. Do not estimate savings or admissions avoided.
- Do not promise the action will work. It is a recommendation for the owning team to accept or decline.
- Write to the contact given. Do not name any other team, and do not address the facility.
- Plain words, no jargon, no greeting line and no signature."""


def ai_enabled() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def facts(hotspot: dict, rec: dict) -> dict:
    """Everything Claude is given for one recommendation."""
    c = rec["cause"]
    return {"hotspot": {k: hotspot[k] for k in ("title", "where", "period", "reported", "expected", "excess")},
            "confirmed_cause": {"name": c["label"], "how_it_could_lead_to_admissions": c["why"], "evidence_rated": c["strength"],
                                "confirmed_by": c["confirmed_by"], "confirmed_on": _when(c["confirmed_at"]),
                                "evidence": [i["title"] for i in c["items"]]},
            "owner": rec["owner"], "contact": rec["contact_role"], "standard_recommendation": rec["standard"],
            "entry_status": rec["status"]}


def check_draft(draft: dict, given: dict) -> str | None:
    """The reason Claude's draft must be rejected, or None if it is fine."""
    text = str(draft.get("recommendation", "")).strip()
    subject, body = str(draft.get("subject", "")).strip(), str(draft.get("body", "")).strip()
    if not text or not subject or not body:
        return "it left the recommendation or the message empty"
    if len(text) > MAX_AI_TEXT or len(SENTENCE_END.findall(text)) > MAX_AI_SENTENCES:
        return "the recommendation was longer than one or two plain sentences"
    if len(body) > MAX_AI_BODY or len(subject) > MAX_SUBJECT:
        return "the message was too long"
    everything = f"{text} {subject} {body}"
    promise = PROMISE.search(everything)
    if promise:
        return f"it promised the action would work (\"{promise.group(0)}\")"
    mine = given["owner"].split(",")[0].lower()
    for other in {o.split(",")[0].lower() for o in OWNERS} - {mine}:
        if other in everything.lower():
            return f"it named a team the rules did not choose ({other})"
    allowed = {m.replace(",", "") for m in NUMBER.findall(json.dumps(given))}
    for token in NUMBER.findall(everything):
        if token.replace(",", "").rstrip(".") not in allowed:
            return f"it used a number it was not given ({token})"
    return None


def _parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    return json.loads(text)


def tailor(hotspot: dict, rec: dict) -> dict:
    """What Claude wrote for one recommendation, or why the standard wording is used. Safe to cache."""
    if rec["outcome"] != "action":
        return {"written_by": "standard", "note": "Standard wording from the mapping. AI does not reword an entry that recommends no action."}
    if not ai_enabled():
        return {"written_by": "standard", "note": "Standard wording from the mapping. Set an Anthropic API key to have Claude reword it for this hotspot and draft the hand-off message."}
    try:
        import anthropic

        given = facts(hotspot, rec)
        reply = anthropic.Anthropic().messages.create(
            model=os.environ.get("CLINICAL_SIGNAL_ACTION_MODEL", config.ACTION_MODEL),
            max_tokens=700, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(given, indent=2)}],
        )
        draft = _parse("\n".join(b.text for b in reply.content if getattr(b, "type", "") == "text"))
        if not isinstance(draft, dict):
            raise ValueError("not an object")
    except Exception as exc:  # no network, bad key, a reply that is not JSON: the tab still works
        return {"written_by": "standard", "note": f"Claude's draft could not be used ({type(exc).__name__}), so the standard wording from the mapping is shown."}
    problem = check_draft(draft, given)
    if problem:
        return {"written_by": "standard", "note": f"Claude's draft was rejected because {problem}, so the standard wording from the mapping is shown."}
    return {"written_by": "claude", "text": draft["recommendation"].strip(),
            "message": {"subject": draft["subject"].strip(), "body": draft["body"].strip()},
            "note": "Fixed rules chose the owner and the recommendation. Claude reworded it for this hotspot and drafted the hand-off message; both were checked before they were shown."}


def apply_tailoring(rec: dict, written: dict) -> dict:
    rec = dict(rec, written_by=written["written_by"], ai_note=written["note"])
    if written["written_by"] == "claude":
        rec["text"] = written["text"]
        rec["message"] = dict(written["message"], to=f"{rec['contact_role']}, {rec['owner']}")
    return rec


# --------------------------------------------------------------------------- people's decisions
class Decisions:
    """What people decided about each recommendation, kept against the data date, the hotspot and the kind of cause."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.DATA_DIR / DECISIONS_FILE)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {}  # an unreadable file is treated as no decisions, never as a crash

    @staticmethod
    def _key(as_of, alert_id: str, topic: str) -> str:
        return f"{as_of}|{alert_id}|{topic}"

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get(self, as_of, alert_id: str, topic: str) -> dict | None:
        return self._data.get(self._key(as_of, alert_id, topic))

    def decide(self, as_of, alert_id: str, topic: str, decision: str | None, text: str = "", edited: bool = False,
               reviewer: str = "", note: str = "") -> dict | None:
        """Accept or decline a recommendation. None clears the decision and everything that followed it."""
        key = self._key(as_of, alert_id, topic)
        with self._lock:
            if decision is None:
                self._data.pop(key, None)
            else:
                if decision not in DECISIONS:
                    raise ValueError("Unknown decision.")
                self._data[key] = {"decision": decision, "text": (text or "").strip()[:MAX_TEXT], "edited": bool(edited),
                                   "reviewer": (reviewer or "").strip()[:MAX_NAME] or "Unnamed reviewer",
                                   "note": (note or "").strip()[:MAX_NOTE], "at": datetime.now().isoformat(timespec="seconds"),
                                   "handoff": None, "answer": None}
            self._save()
            return self._data.get(key)

    def hand_off(self, as_of, alert_id: str, topic: str, message: dict | None) -> dict:
        """Record that the analyst sent the message themselves. None undoes it. The app never sends anything."""
        key = self._key(as_of, alert_id, topic)
        with self._lock:
            rec = self._data.get(key)
            if not rec or rec["decision"] != "accepted":
                raise ValueError("Only an accepted recommendation can be handed off.")
            if message is None:
                rec["handoff"], rec["answer"] = None, None
            else:
                rec["handoff"] = {"to": str(message.get("to", ""))[:MAX_SUBJECT], "subject": str(message.get("subject", "")).strip()[:MAX_SUBJECT],
                                  "body": str(message.get("body", "")).strip()[:MAX_BODY], "at": datetime.now().isoformat(timespec="seconds")}
            self._save()
            return rec

    def answer(self, as_of, alert_id: str, topic: str, answer: str | None, note: str = "") -> dict:
        """Record what the owner's point of contact said. None clears it."""
        key = self._key(as_of, alert_id, topic)
        with self._lock:
            rec = self._data.get(key)
            if not rec or not rec.get("handoff"):
                raise ValueError("The owner can only answer a recommendation that was handed off.")
            if answer is None:
                rec["answer"] = None
            else:
                if answer not in ANSWERS:
                    raise ValueError("Unknown answer.")
                rec["answer"] = {"answer": answer, "note": (note or "").strip()[:MAX_NOTE], "at": datetime.now().isoformat(timespec="seconds")}
            self._save()
            return rec

    def earlier(self, as_of, alert_id: str, topic: str) -> dict | None:
        """The most recent hand-off for the same hotspot and cause on an earlier day's data, if there was one."""
        today, best = str(as_of), None
        for key, rec in self._data.items():
            day, a, t = key.split("|", 2)
            if a == alert_id and t == topic and day < today and rec.get("handoff") and (best is None or day > best["as_of"]):
                best = {"as_of": day, "handed_off_at": rec["handoff"]["at"], "to": rec["handoff"]["to"],
                        "answer": (rec.get("answer") or {}).get("answer"),
                        "days": (date.fromisoformat(today) - date.fromisoformat(day)).days}
        return best

    def attach(self, as_of, alert_id: str, result: dict) -> dict:
        """Add each recommendation's decision, its stage, and the message to send, without changing `result`."""
        out = dict(result)
        recs = []
        for r in result["recommendations"]:
            d = self.get(as_of, alert_id, r["topic"])
            r = dict(r, decision=d, earlier=self.earlier(as_of, alert_id, r["topic"]))
            if not d:
                r["stage"] = "to_decide"
            elif d["decision"] == "declined":
                r["stage"] = "declined"
            elif not d.get("handoff"):
                r["stage"] = "accepted"
                # Claude's message was written for Claude's wording. If the analyst changed the wording, the standard message carries theirs.
                r["draft"] = r["message"] if (r.get("message") and not d["edited"]) else standard_message(result["hotspot"], r, d["text"] or r["text"])
                r["draft_by"] = "claude" if (r.get("message") and not d["edited"]) else "standard"
            else:
                r["stage"] = {"agreed": "agreed", "declined": "owner_declined"}.get((d.get("answer") or {}).get("answer"), "handed_off")
            recs.append(r)
        out["recommendations"] = recs
        return out
