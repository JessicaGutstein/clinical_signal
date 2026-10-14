"""Web pages and the JSON endpoints the page calls."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, send_from_directory

import config
from . import actions, causes, reviews, summary
from .detection import public

bp = Blueprint("main", __name__)


def _engine():
    return current_app.extensions["engine"]


def _lob() -> str:
    """Detection always covers every admission together. The data still carries a
    line of business on each admission, but the app does not split or filter by it."""
    return "all"


@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/api/overview")
def overview():
    """Everything the first screen needs: the alerts and every facility's bubble."""
    engine, lob = _engine(), _lob()
    det, ds = engine.run(lob), engine.ds
    window = config.WINDOW_DAYS
    reported = det.raw[:, :, :window].sum()
    return jsonify({
        "meta": {
            "as_of": ds.as_of.isoformat(),
            "window_start": (ds.as_of - timedelta(days=window - 1)).isoformat(),
            "window_days": window,
            "admissions_reported": int(round(reported)),
            "top_n": config.TOP_N,
            "z_gate": config.Z_GATE,
            "min_excess": config.MIN_EXCESS,
            "n_facilities": len(det.facilities),
            "ai_summary": summary.ai_enabled(),
            "outside": causes.counts_by_source(current_app.extensions["outside"]),
            "mapping": actions.summary(current_app.extensions["mapping"]),
            "ai_actions": actions.ai_enabled(),
        },
        "alerts": [public(a) for a in det.alerts],
        "facilities": det.facilities,
    })


@bp.get("/api/alerts/<alert_id>")
def alert_detail(alert_id: str):
    """Evidence for one alert, including its 12-month chart."""
    detail = _engine().alert_detail(_lob(), alert_id)
    if detail is None:
        abort(404, description="No such alert for this filter.")
    return jsonify(detail)


@bp.get("/api/alerts/<alert_id>/summary")
def alert_summary(alert_id: str):
    """Plain-language summary of one alert. Cached so each is written once."""
    engine, lob = _engine(), _lob()
    alert = engine.run(lob).by_id.get(alert_id)
    if alert is None:
        abort(404, description="No such alert for this filter.")
    cache = current_app.extensions["summaries"]
    key = (lob, alert_id)
    if key not in cache:
        # A hotspot at one hospital is described with that hospital's type and area.
        facility = None
        if alert["kind"] in ("pair", "facility", "facility_wide"):
            facility = next(f for f in engine.run(lob).facilities if f["id"] == alert["facility_ids"][0])
        cache[key] = summary.write_summary(alert, facility)
    return jsonify(cache[key])


def _causes(alert_id: str):
    """Possible causes for one alert, from the outside items. Worked out once and cached."""
    engine, lob = _engine(), _lob()
    det = engine.run(lob)
    alert = det.by_id.get(alert_id)
    if alert is None:
        abort(404, description="No such alert for this filter.")
    cache = current_app.extensions["causes"]
    if alert_id not in cache:
        cache[alert_id] = causes.find(alert, det.facilities, engine.ds.as_of, current_app.extensions["outside"])
    return engine.ds.as_of.isoformat(), cache[alert_id]


@bp.get("/api/alerts/<alert_id>/causes")
def alert_causes(alert_id: str):
    """Part two: what may be driving one alert, with any decisions people have made."""
    as_of, found = _causes(alert_id)
    return jsonify(current_app.extensions["reviews"].attach(as_of, alert_id, found))


@bp.post("/api/alerts/<alert_id>/causes/<topic>/review")
def review_cause(alert_id: str, topic: str):
    """A person confirms, rejects, or is not sure about one possible cause. A decision of null clears it."""
    as_of, found = _causes(alert_id)
    if topic not in {c["topic"] for c in found["causes"]}:
        abort(404, description="No such possible cause for this alert.")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision is not None and decision not in reviews.DECISIONS:
        abort(400, description="Unknown decision.")
    store = current_app.extensions["reviews"]
    store.set(as_of, alert_id, topic, decision, str(body.get("reviewer") or ""), str(body.get("note") or ""))
    return jsonify(next(c for c in store.attach(as_of, alert_id, found)["causes"] if c["topic"] == topic))


def _actions(alert_id: str):
    """Part three for one alert: the owner and recommendation for each confirmed cause, with people's decisions."""
    as_of, found = _causes(alert_id)
    engine = _engine()
    det = engine.run(_lob())
    alert = det.by_id[alert_id]
    found = current_app.extensions["reviews"].attach(as_of, alert_id, found)
    result = actions.recommend(alert, det.facilities, found, current_app.extensions["mapping"])
    cache = current_app.extensions["tailored"]
    recs = []
    for rec in result["recommendations"]:
        # Claude's wording is written once for a hotspot, cause and confirmation, then reused.
        key = (alert_id, rec["topic"], rec["condition"], rec["cause"]["confirmed_at"])
        if key not in cache:
            cache[key] = actions.tailor(result["hotspot"], rec)
        recs.append(actions.apply_tailoring(rec, cache[key]))
    result["recommendations"] = recs
    result["as_of"] = as_of
    return as_of, current_app.extensions["decisions"].attach(as_of, alert_id, result)


@bp.get("/api/alerts/<alert_id>/actions")
def alert_actions(alert_id: str):
    return jsonify(_actions(alert_id)[1])


@bp.post("/api/alerts/<alert_id>/actions/<topic>/<step>")
def act(alert_id: str, topic: str, step: str):
    """A person's step on one recommendation: decide on it, mark it handed off, or record the owner's answer.
    Nothing here sends a message to anyone."""
    as_of, result = _actions(alert_id)
    rec = next((r for r in result["recommendations"] if r["topic"] == topic), None)
    if rec is None:
        abort(404, description="No recommendation for that cause. A cause must be confirmed first.")
    body = request.get_json(silent=True) or {}
    store = current_app.extensions["decisions"]
    try:
        if step == "decision":
            text = str(body.get("text") or "").strip() or rec["text"]
            store.decide(as_of, alert_id, topic, body.get("decision"), text, text != rec["text"],
                         str(body.get("reviewer") or ""), str(body.get("note") or ""))
        elif step == "handoff":
            message = None
            if not body.get("undo"):
                # The person may edit the subject and the text. Who it goes to is set by the mapping.
                message = {"to": f"{rec['contact_role']}, {rec['owner']}", "subject": body.get("subject") or "", "body": body.get("body") or ""}
                if not str(message["body"]).strip():
                    abort(400, description="The message is empty.")
            store.hand_off(as_of, alert_id, topic, message)
        elif step == "answer":
            store.answer(as_of, alert_id, topic, body.get("answer"), str(body.get("note") or ""))
        else:
            abort(404, description="Unknown step.")
    except ValueError as exc:
        abort(400, description=str(exc))
    return jsonify(_actions(alert_id)[1])


@bp.get("/external/")
def external_index():
    """The list of every outside item. Stands in for the outside world in this prototype."""
    return send_from_directory(config.EXTERNAL_DIR, "index.html")


@bp.get("/external")
def external_index_bare():
    return redirect("/external/")


@bp.get("/external/index.html")
def external_index_file():
    return send_from_directory(config.EXTERNAL_DIR, "index.html")


@bp.get("/external/articles/<item_id>.html")
def external_article(item_id: str):
    """One outside item as a page. Only pages for items that are loaded can be opened."""
    if item_id not in {i["id"] for i in current_app.extensions["outside"]}:
        abort(404, description="No such outside item.")
    return send_from_directory(config.EXTERNAL_DIR / "articles", f"{item_id}.html")


@bp.get("/api/facilities/<facility_id>")
def facility_detail(facility_id: str):
    """What the queue shows when a bubble is clicked."""
    engine = _engine()
    if facility_id not in set(engine.ds.facilities["facility_id"]):
        abort(404, description="No such facility.")
    return jsonify(engine.facility_detail(_lob(), facility_id))


@bp.get("/api/codes")
def codes():
    """Top ICD-10 codes for the facilities named (or all), in one diagnosis group,
    several (repeat the `diagnosis` parameter), or every group (`diagnosis=all`)."""
    engine, lob = _engine(), _lob()
    wanted_dx = request.args.getlist("diagnosis")
    if wanted_dx == ["all"]:
        diagnoses = None
    else:
        diagnoses = wanted_dx
        if not diagnoses or any(d not in engine.ds.diagnoses for d in diagnoses):
            abort(400, description="Unknown diagnosis group.")
    wanted = request.args.get("facilities", "all")
    facility_ids = None
    if wanted != "all":
        facility_ids = [f for f in wanted.split(",") if f]
        known = set(engine.ds.facilities["facility_id"])
        if not facility_ids or any(f not in known for f in facility_ids):
            abort(400, description="Unknown facility.")
    return jsonify(engine.code_breakdown(lob, facility_ids, diagnoses))


@bp.app_errorhandler(400)
@bp.app_errorhandler(404)
def api_error(err):
    if request.path.startswith("/api/"):
        return jsonify({"error": err.description}), err.code
    return err
