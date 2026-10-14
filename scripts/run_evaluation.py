"""Scores detection against the evaluation set.

    python scripts/run_evaluation.py [results.json]

Reads data/planted_hotspots_answer_key.csv. Each row is a case with an expected
outcome that was written down before detection was run on it:

    H..  a pattern planted in the data that SHOULD be flagged
    D..  a decoy planted in the data that should NOT be flagged
    P.., R..  detection replayed on an earlier date, or a past event checked today
    S..  a rule that must hold whatever the data says

It prints one line per case, then how many alerts have no planted pattern behind
them (the false alarms). Nothing here is used by the web app.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from clinical_signal.data_loader import load  # noqa: E402
from clinical_signal.detection.engine import Engine  # noqa: E402

KEY_FILE = "planted_hotspots_answer_key.csv"
_runs: dict = {}


def detection(as_of: str | None):
    """Detection for a date (None is today's data), run once per date."""
    if as_of not in _runs:
        ds = load(as_of=as_of or None)
        _runs[as_of] = (ds, Engine(ds).run("all"))
    return _runs[as_of]


def covering(det, ds, facility: str, diagnosis: str | None) -> list:
    """Alerts that involve this hospital and, when given, this diagnosis group."""
    fid = dict(zip(ds.facilities["facility_name"], ds.facilities["facility_id"]))[facility]
    hits = []
    for a in det.alerts:
        if fid not in a["facility_ids"] or a["kind"] == "plan_wide":
            continue
        if diagnosis is None:
            if a["kind"] in ("facility", "facility_wide"):
                hits.append(a)
        elif a["diagnosis"] == diagnosis or any(m["diagnosis"] == diagnosis for m in a["members"] if a["kind"] == "facility"):
            hits.append(a)
    return hits


def _planted_now(key: pd.DataFrame) -> dict:
    """Hospital -> diagnosis groups (None for all) with a pattern planted in today's window."""
    out: dict = {}
    for _, r in key.iterrows():
        if not r["id"][0] in "HD" or r["should_alert"] != "Yes":
            continue
        for f in r["facilities"].split("; "):
            out.setdefault(f, set()).update([None] if r["diagnosis_group"] == "All" else r["diagnosis_group"].split("; "))
    return out


def evaluate() -> tuple[list[dict], dict]:
    key = pd.read_csv(config.DATA_DIR / KEY_FILE, dtype=str, keep_default_na=False)
    results = []
    for _, r in key.iterrows():
        cid, want = r["id"], r["should_alert"].startswith("Yes")
        ds, det = detection(r["replay_as_of"] or None)
        facs = [] if r["facilities"] == "Plan-wide" else r["facilities"].split("; ")
        dxs = None if r["diagnosis_group"] in ("All", "Their planted diagnoses") else r["diagnosis_group"].split("; ")
        got, found = "", None

        if cid == "S1":
            n = sum(a["priority"] == "high" for a in det.alerts)
            found, got = n <= config.TOP_N, f"{n} top hotspots"
        elif cid == "S2":
            hits = covering(det, ds, facs[0], None)
            found, got = len(hits) == 1, f"{len(hits)} hotspot(s) for the facility"
        elif cid == "S3":
            low = [a for a in det.alerts if a["display"]["excess"] < min(config.MIN_EXCESS.values())]
            found, got = not low, f"{len(low)} alert(s) under the minimum"
        elif cid == "R3":
            hits = [a for a in det.alerts if a["kind"] == "plan_wide" and a["diagnosis"] == dxs[0]]
            found, got = bool(hits), f"{len(hits)} plan-wide flu alert(s) on {r['replay_as_of']}"
        elif cid == "R4":
            planted = _planted_now(key)
            hits = [a for f in facs for dx in planted.get(f, []) for a in covering(det, ds, f, dx)]
            found, got = bool(hits), f"{len(hits)} early alert(s)"
        else:
            per = [covering(det, ds, f, dx) for f in facs for dx in (dxs or [None])]
            covered = sum(bool(h) for h in per)
            alerts = {a["id"]: a for h in per for a in h}
            ranks = sorted(a["rank"] for a in alerts.values())
            shape = r["expected_shape"]
            one = next(iter(alerts.values())) if len(alerts) == 1 else None
            if shape.startswith("At least one"):
                found = covered >= 1
            elif shape == "Large facility only":      # the first facility named is the large one
                found = bool(per[0]) and not any(a["kind"] == "wave" for a in alerts.values())
            elif shape == "Two separate alerts":
                found = covered == len(per) and len(alerts) == len(per) and not any(a["kind"] == "wave" for a in alerts.values())
            elif want:
                found = covered == len(per)
                if "grouped" in shape:
                    found = found and one is not None and one["kind"] == "wave" and one.get("grouped_by") == "area"
                if "system-wide" in shape:
                    found = found and one is not None and one.get("grouped_by") == "system"
            else:
                found = covered > 0
            got = (f"{covered} of {len(per)} flagged" if len(per) > 1 else ("flagged" if covered else "not flagged"))
            if ranks:
                got += f", rank {', '.join(map(str, ranks))}"
            if one is not None and one.get("grouped_by") == "system":
                got += " (one system-wide hotspot)"
            elif want and dxs and len(facs) == 1:
                whole = covering(det, ds, facs[0], None)
                if whole:  # caught, but not under the diagnosis that was planted
                    got += f" for this diagnosis; the facility as a whole is flagged, rank {whole[0]['rank']}"

        # "found" means the thing the case is about was seen; a case passes when that matches what was wanted.
        passed = found == want if cid[0] != "S" else bool(found)
        results.append({"id": cid, "pattern": r["pattern"], "expected": "Flag it" if want and cid[0] != "S" else "Holds" if cid[0] == "S" else "Do not flag",
                        "got": got, "passed": bool(passed)})

    # Alerts today with nothing planted behind them.
    ds, det = detection(None)
    planted = _planted_now(key)
    name = dict(zip(ds.facilities["facility_id"], ds.facilities["facility_name"]))

    def explained(a) -> bool:
        for fid in a["facility_ids"]:
            dxs = planted.get(name[fid])
            if dxs and (None in dxs or a["diagnosis"] in dxs or a["kind"] in ("facility", "facility_wide")):
                return True
        return False

    stray = [a for a in det.alerts if not explained(a)]
    summary = {
        "cases": len(results), "passed": sum(r["passed"] for r in results),
        "alerts": len(det.alerts), "unplanted": len(stray),
        "top": sum(a["priority"] == "high" for a in det.alerts),
        "unplanted_top": sum(a["priority"] == "high" for a in stray),
        "unplanted_list": [(a["rank"], a["title"], a["subtitle"]) for a in stray],
    }
    return results, summary


def main() -> int:
    results, s = evaluate()
    if len(sys.argv) > 1:  # also save the results, for the test record
        import json
        Path(sys.argv[1]).write_text(json.dumps({"results": results, "summary": s}, indent=1))
    width = max(len(r["pattern"]) for r in results)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'MISS'}  {r['id']:<4} {r['pattern']:<{width}}  expected: {r['expected']:<11}  got: {r['got']}")
    print(f"\n{s['passed']} of {s['cases']} cases behave as expected.")
    print(f"{s['alerts']} alerts today; {s['unplanted']} have no planted pattern behind them "
          f"({s['unplanted_top']} of the {s['top']} top hotspots).")
    if len(sys.argv) > 1:  # also save the results, for the evaluation log
        import json
        Path(sys.argv[1]).write_text(json.dumps({"results": results, "summary": s}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
