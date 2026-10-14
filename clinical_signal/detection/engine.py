"""Runs hotspot detection end to end.

    1. Take the reported admissions as they are (config can switch on an
       adjustment for reports still to come; it is off).
    2. Run the four comparisons on every facility x diagnosis pair, every
       facility, and every diagnosis group.
    3. Roll related pairs up so one event is one alert.
    4. Rank the alerts and mark the top ones as high priority.
    5. Work out what each facility's bubble should show.

Detection is fully deterministic: the same data always produces the same alerts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

import config
from ..data_loader import Dataset
from . import comparisons as cmp
from .ranking import rank
from .rollup import group_pairs

W = config.WINDOW_DAYS


def _whole(observed, expected):
    """Whole-number figures for display, kept consistent with each other."""
    if observed is None:
        return {"observed": None, "expected": None, "excess": None}
    o = int(round(observed))
    if expected is None:
        return {"observed": o, "expected": None, "excess": None}
    e = int(round(expected))
    return {"observed": o, "expected": e, "excess": o - e}


def _r(v, digits=1):
    """Round for display; None when there is no value."""
    if v is None or not np.isfinite(v):
        return None
    return round(float(v), digits)


@dataclass
class Detection:
    lob: str
    growth: float
    completeness_window: float
    completeness_week: float
    raw: np.ndarray                     # [facility, diagnosis, age] reported
    adj: np.ndarray                     # [facility, diagnosis, age] what detection runs on (same as raw by default)
    pair: dict                          # comparison results per pair, index f * D + d
    fac: dict                           # comparison results per facility
    alerts: list = field(default_factory=list)
    by_id: dict = field(default_factory=dict)
    facilities: list = field(default_factory=list)


class Engine:
    def __init__(self, dataset: Dataset):
        self.ds = dataset
        self._cache: dict[str, Detection] = {}
        self.F = len(dataset.facilities)
        self.D = len(dataset.diagnoses)
        self.fac_rows = dataset.facilities.to_dict("records")
        self.areas = [r["area"] for r in self.fac_rows]
        self.systems = [r["health_system"] for r in self.fac_rows]

    # ------------------------------------------------------------------ run
    def run(self, lob: str = "all") -> Detection:
        if lob not in self._cache:
            self._cache[lob] = self._detect(lob)
        return self._cache[lob]

    def _detect(self, lob: str) -> Detection:
        ds = self.ds
        raw = ds.counts.sum(axis=0) if lob == "all" else ds.counts[ds.lobs.index(lob)]
        # Detection runs on reported admissions unless the reporting-lag adjustment is switched on.
        adj = raw / ds.completeness[None, None, :] if config.ADJUST_FOR_REPORTING_LAG else raw
        total = adj.sum(axis=(0, 1))
        growth = cmp.growth_factor(total)

        pair = cmp.evaluate(adj.reshape(self.F * self.D, -1), config.MIN_EXCESS["pair"], growth)
        fac = cmp.evaluate(adj.sum(axis=1), config.MIN_EXCESS["facility"], growth)
        dx = cmp.evaluate(adj.sum(axis=0), config.MIN_EXCESS["diagnosis"], growth)

        raw_total = raw.sum(axis=(0, 1))
        det = Detection(
            lob=lob, growth=growth,
            completeness_window=float(raw_total[:W].sum() / max(total[:W].sum(), 1e-9)),
            completeness_week=float(raw_total[:7].sum() / max(total[:7].sum(), 1e-9)),
            raw=raw, adj=adj, pair=pair, fac=fac,
        )

        flagged = pair["flagged"].reshape(self.F, self.D)
        regular = adj[:, :, :cmp.YEAR].sum(axis=-1) >= config.REGULAR_ADMITS_PER_YEAR
        groups = group_pairs(flagged, self.areas, regular, self.systems)

        alerts = []
        for f, d in groups["single"]:
            alerts.append(self._pair_alert(det, f, d))
        for (d, area), fs in groups["wave"].items():
            alerts.append(self._wave_alert(det, d, area, fs))
        for (d, system), fs in groups["system"].items():
            alerts.append(self._wave_alert(det, d, None, fs, system=system))
        for f, ds_ in groups["facility"].items():
            alerts.append(self._facility_rollup_alert(det, f, ds_))
        alerts += self._parent_alerts(det, fac, dx, alerts, set(groups["facility"]))

        det.alerts = rank(alerts)
        det.by_id = {a["id"]: a for a in det.alerts}
        det.facilities = self._facility_summaries(det)
        return det

    # ------------------------------------------------------- slice statistics
    def _stats(self, ev: dict, i: int) -> dict:
        """Readable results of the four comparisons for one slice."""
        comps = []
        for key, label in cmp.COMPARISONS:
            c = ev[key]
            comps.append({
                "key": key, "label": label,
                "observed": _r(c["observed"][i]), "expected": _r(c["expected"][i]),
                "excess": _r(c["excess"][i]), "z": _r(c["z"][i], 2),
                "fired": bool(c["fired"][i]),
                "period": cmp.PERIODS[key][0], "baseline": cmp.PERIODS[key][2],
            })
            comps[-1]["display"] = _whole(comps[-1]["observed"], comps[-1]["expected"])
            if "season_factor" in c:  # how much of a rise past years show is normal right now
                comps[-1]["season_factor"] = _r(c["season_factor"][i], 2)
        n_fired = int(ev["n_fired"][i])
        if n_fired:
            p = int(ev["primary"][i])
        else:  # nothing fired: describe the slice against its seasonal norm
            p = 0 if comps[0]["expected"] is not None else 1
        head = comps[p]
        return {
            "observed": head["observed"], "expected": head["expected"], "excess": head["excess"],
            "display": head["display"],
            "primary": head["key"], "primary_label": head["label"],
            "period": head["period"], "baseline": head["baseline"],
            "comparisons": comps, "n_fired": n_fired,
            "weekly4": [_r(v) for v in ev["weekly4"][i]],
            "slope": _r(ev["trend"]["slope"][i]),
            "_phi": float(ev["phi"][i]),
        }

    def _finish(self, det: Detection, alert: dict, mask: np.ndarray) -> dict:
        """Add the figures every alert carries: reports received, completeness, spend."""
        days = cmp.PERIODS[alert["primary"]][1]
        reported = det.raw[mask][:, :days].sum()
        adjusted = det.adj[mask][:, :days].sum()
        alert["reported"] = int(round(reported))
        alert["completeness"] = _r(reported / adjusted if adjusted > 0 else det.completeness_window, 3)
        weight = det.adj[mask][:, :W].sum(axis=-1)
        cost = self.ds.avg_paid[mask]
        avg_cost = float((cost * weight).sum() / weight.sum()) if weight.sum() > 0 else float(cost.mean())
        alert["avg_cost"] = round(avg_cost)
        alert["excess_spend"] = round(max(alert["excess"], 0) * avg_cost)
        alert["_mask"] = mask
        return alert

    def _pair_mask(self, pairs) -> np.ndarray:
        mask = np.zeros((self.F, self.D), dtype=bool)
        for f, d in pairs:
            mask[f, d] = True
        return mask

    def _member(self, det: Detection, f: int, d: int, key: str | None = None) -> dict:
        """One facility x diagnosis line inside a rolled-up alert."""
        s = self._stats(det.pair, f * self.D + d)
        if key:  # report against the parent's comparison instead of the pair's own
            c = next(c for c in s["comparisons"] if c["key"] == key)
            s.update(observed=c["observed"], expected=c["expected"], excess=c["excess"],
                     display=c["display"], period=c["period"])
        row = self.fac_rows[f]
        return {
            "facility_id": row["facility_id"], "facility": row["facility_name"],
            "short_name": row["short_name"], "diagnosis": self.ds.diagnoses[d],
            "observed": s["observed"], "expected": s["expected"], "excess": s["excess"],
            "display": s["display"], "n_fired": s["n_fired"], "period": s["period"],
        }

    # ----------------------------------------------------------- alert kinds
    def _pair_alert(self, det, f, d) -> dict:
        row, dx_name = self.fac_rows[f], self.ds.diagnoses[d]
        a = self._stats(det.pair, f * self.D + d)
        a.update(
            id=f"pair-{row['facility_id']}-{d}", kind="pair", title=dx_name,
            subtitle=row["facility_name"], diagnosis=dx_name, area=row["area"],
            avoidable=self.ds.avoidable[dx_name], facility_ids=[row["facility_id"]], members=[],
            _contrib=[(f, a["excess"], a["n_fired"])],
        )
        return self._finish(det, a, self._pair_mask([(f, d)]))

    def _wave_alert(self, det, d, area, fs, system=None) -> dict:
        """One hotspot for the same diagnosis at several facilities: in one area, or,
        when `system` is given, across one health system."""
        dx_name = self.ds.diagnoses[d]
        mask = self._pair_mask([(f, d) for f in fs])
        ev = cmp.evaluate(det.adj[mask].sum(axis=0)[None, :], config.MIN_EXCESS["group"], det.growth)
        a = self._stats(ev, 0)
        members = sorted((self._member(det, f, d) for f in fs), key=lambda m: -m["excess"])
        a.update(
            id=f"{'system' if system else 'wave'}-{d}-{re.sub(r'[^A-Za-z0-9]+', '_', system or area)}", kind="wave", title=dx_name,
            subtitle=f"{len(fs)} facilities of {system}" if system else f"{len(fs)} facilities in {'the Bronx' if area == 'Bronx' else area}",
            diagnosis=dx_name, area=area, system=system, grouped_by="system" if system else "area",
            avoidable=self.ds.avoidable[dx_name],
            facility_ids=[m["facility_id"] for m in members], members=members,
            _contrib=[(f, self._stats(det.pair, f * self.D + d)["excess"],
                       int(det.pair["n_fired"][f * self.D + d])) for f in fs],
        )
        return self._finish(det, a, mask)

    def _facility_rollup_alert(self, det, f, ds_) -> dict:
        row = self.fac_rows[f]
        if det.fac["flagged"][f]:  # the whole facility is up: describe all admissions
            a = self._stats(det.fac, f)
            mask = np.zeros((self.F, self.D), dtype=bool)
            mask[f, :] = True
            scope = "all admissions"
        else:                       # only the flagged groups are up
            mask = self._pair_mask([(f, d) for d in ds_])
            ev = cmp.evaluate(det.adj[mask].sum(axis=0)[None, :], config.MIN_EXCESS["group"], det.growth)
            a = self._stats(ev, 0)
            scope = "flagged groups"
        members = sorted((self._member(det, f, d) for d in ds_), key=lambda m: -m["excess"])
        a.update(
            id=f"facility-{row['facility_id']}", kind="facility",
            title=f"{len(ds_)} diagnosis groups elevated", subtitle=row["facility_name"],
            diagnosis=None, area=row["area"], avoidable=False, scope=scope,
            facility_ids=[row["facility_id"]], members=members,
            _contrib=[(f, a["excess"], a["n_fired"])],
        )
        return self._finish(det, a, mask)

    def _parent_alerts(self, det, fac, dx, children, rolled_facilities) -> list:
        """Facility-wide and plan-wide alerts that the specific alerts do not explain.

        A facility can be up by a meaningful amount with the increase spread so
        thinly across diagnoses that no single pair qualifies; the same goes for
        a diagnosis spread across many facilities. Those are kept. Where the
        specific alerts already cover most of the excess, the parent is dropped
        so the same event is not listed twice.
        """
        share = config.PARENT_EXPLAINED_SHARE
        out = []
        for f in np.nonzero(fac["flagged"])[0]:
            f = int(f)
            if f in rolled_facilities:
                continue
            row = self.fac_rows[f]
            a = self._stats(fac, f)
            explained = sum(e for c in children for (cf, e, _) in c["_contrib"] if cf == f)
            if explained >= share * a["excess"]:
                continue
            top = np.argsort(-det.pair[a["primary"]]["excess"].reshape(self.F, self.D)[f])[:5]
            a.update(
                id=f"facilitywide-{row['facility_id']}", kind="facility_wide",
                title="All admissions", subtitle=row["facility_name"], diagnosis=None,
                area=row["area"], avoidable=False, facility_ids=[row["facility_id"]],
                members=[self._member(det, f, int(d), a["primary"]) for d in top],
                _contrib=[(f, a["excess"], a["n_fired"])],
            )
            mask = np.zeros((self.F, self.D), dtype=bool)
            mask[f, :] = True
            out.append(self._finish(det, a, mask))

        for d in np.nonzero(dx["flagged"])[0]:
            d = int(d)
            dx_name = self.ds.diagnoses[d]
            a = self._stats(dx, d)
            explained = sum(c["excess"] for c in children if c.get("diagnosis") == dx_name)
            if explained >= share * a["excess"]:
                continue
            top = np.argsort(-det.pair[a["primary"]]["excess"].reshape(self.F, self.D)[:, d])[:5]
            members = [self._member(det, int(f), d, a["primary"]) for f in top]
            a.update(
                id=f"planwide-{d}", kind="plan_wide", title=dx_name,
                subtitle="Plan-wide, across all facilities", diagnosis=dx_name, area=None,
                avoidable=self.ds.avoidable[dx_name],
                facility_ids=[m["facility_id"] for m in members], members=members, _contrib=[],
            )
            mask = np.zeros((self.F, self.D), dtype=bool)
            mask[:, d] = True
            out.append(self._finish(det, a, mask))
        return out

    # ------------------------------------------------------------ facilities
    def _facility_summaries(self, det: Detection) -> list:
        """What each bubble on the map shows."""
        per = {f: {"high": [], "low": [], "excess": {"high": 0.0, "low": 0.0},
                   "fired": {"high": 0, "low": 0}} for f in range(self.F)}
        for a in det.alerts:
            p = a["priority"]
            for f, excess, n_fired in a["_contrib"]:
                per[f][p].append(a["id"])
                per[f]["excess"][p] += max(excess or 0.0, 0.0)
                per[f]["fired"][p] = max(per[f]["fired"][p], n_fired)
        out = []
        for f, row in enumerate(self.fac_rows):
            info = per[f]
            status = "high" if info["high"] else "low" if info["low"] else "none"
            # The bubble's own totals are always the 28-day window against the
            # seasonal norm, whichever comparison an alert here happened to lead with.
            comps = self._stats(det.fac, f)["comparisons"]
            total = comps[0] if comps[0]["expected"] is not None else comps[1]
            out.append({
                "id": row["facility_id"], "name": row["facility_name"], "short_name": row["short_name"],
                "type": row["facility_type"], "system": row["health_system"], "network": row["network_status"],
                "borough": row["borough"], "county": row["county"],
                "area_members": self.ds.membership.get(row["area"], {}).get("members"),
                "area_members_year_ago": self.ds.membership.get(row["area"], {}).get("year_ago"),
                "area": row["area"], "lat": row["latitude"], "lon": row["longitude"],
                "status": status,
                "excess": _r(info["excess"][status]) if status != "none" else 0,
                "n_fired": info["fired"][status] if status != "none" else 0,
                "high_alerts": info["high"], "low_alerts": info["low"],
                "observed": total["observed"], "expected": total["expected"],
                "display": total["display"],
            })
        return out

    def facility_detail(self, lob: str, facility_id: str) -> dict:
        """Everything the queue shows when a bubble is clicked."""
        det = self.run(lob)
        f = self.ds.facility_index(facility_id)
        summary = det.facilities[f]
        in_alert = set()
        for a in det.alerts:
            if facility_id in a["facility_ids"] and a["kind"] != "plan_wide":
                if a["diagnosis"]:
                    in_alert.add(a["diagnosis"])
                in_alert.update(m["diagnosis"] for m in a["members"] if m["facility_id"] == facility_id)
        activity = []
        for d, dx_name in enumerate(self.ds.diagnoses):
            if dx_name in in_alert:
                continue
            s = self._stats(det.pair, f * self.D + d)
            if (s["observed"] or 0) < 1 and (s["expected"] or 0) < 1:
                continue
            activity.append({"diagnosis": dx_name, "observed": s["observed"],
                             "expected": s["expected"], "excess": s["excess"],
                             "display": s["display"], "avoidable": self.ds.avoidable[dx_name]})
        # Furthest above expected first; ties and normal slices fall back to volume.
        activity.sort(key=lambda r: (-(r["excess"] or 0), -(r["observed"] or 0)))
        return {"facility": summary, "activity": activity[:6]}

    # ----------------------------------------------------------------- codes
    def code_breakdown(self, lob: str, facility_ids: list[str] | None,
                       diagnoses: str | list[str] | None) -> dict:
        """The most common ICD-10 codes in a slice: some or all facilities, and one
        diagnosis group, several, or (with None) every group.

        Purely descriptive: it shows what a slice is made of, and how that compares
        with its usual mix. It is not used to decide what is flagged.
        """
        ds = self.ds
        if isinstance(diagnoses, str):
            diagnoses = [diagnoses]
        groups = list(ds.diagnoses) if diagnoses is None else list(dict.fromkeys(diagnoses))
        sel = slice(None) if lob == "all" else [ds.lobs.index(lob)]
        window_all, prior_all = ds.code_window[sel].sum(axis=0), ds.code_prior[sel].sum(axis=0)
        rows = list(range(self.F)) if facility_ids is None else [ds.facility_index(f) for f in facility_ids]
        cols = np.nonzero(ds.codes["diagnosis_group"].isin(groups).to_numpy())[0]
        dx = [ds.diagnoses.index(g) for g in groups]

        window = window_all[rows][:, cols].sum(axis=0)
        prior = prior_all[rows][:, cols].sum(axis=0)
        total, history = float(window.sum()), float(prior.sum())
        own_history = history >= config.CODE_HISTORY_MIN
        if not own_history:  # too little history here: borrow the plan-wide mix
            prior = prior_all[:, cols].sum(axis=0)
            history = float(prior.sum())
        usual = prior / history if history > 0 else np.zeros_like(prior)

        order = sorted(range(len(cols)), key=lambda i: (-window[i], -usual[i]))
        codes = []
        for i in order[: config.TOP_CODES]:
            if window[i] <= 0:
                break
            c = ds.codes.iloc[cols[i]]
            codes.append({
                "code": c["code"], "name": c["name"], "meaning": c["meaning"], "group": c["diagnosis_group"],
                "count": int(window[i]), "share": round(float(window[i] / total), 3),
                "usual_share": round(float(usual[i]), 3),
            })
        preliminary = float(ds.preliminary[sel].sum(axis=0)[rows][:, dx].sum())
        return {
            "diagnosis": groups[0] if len(groups) == 1 else None,
            "n_groups": len(groups), "all_groups": diagnoses is None,
            "n_facilities": len(rows), "reported": int(total),
            "preliminary": int(preliminary), "window_days": config.WINDOW_DAYS,
            "usual_basis": "own" if own_history else "plan", "codes": codes,
            "n_codes": int((window > 0).sum()),
        }

    # ---------------------------------------------------------------- detail
    def alert_detail(self, lob: str, alert_id: str) -> dict | None:
        det = self.run(lob)
        a = det.by_id.get(alert_id)
        if a is None:
            return None
        series = det.adj[a["_mask"]].sum(axis=0)
        reported = det.raw[a["_mask"]].sum(axis=0)
        rows = cmp.expected_band(series, det.growth, a["_phi"])
        chart = []
        for k, value, exp, low, high in reversed(rows):
            end = self.ds.as_of - timedelta(days=7 * k)
            chart.append({
                "week_start": (end - timedelta(days=6)).isoformat(), "week_end": end.isoformat(),
                "value": _r(value), "reported": int(round(reported[7 * k: 7 * k + 7].sum())),
                "expected": _r(exp), "low": _r(low), "high": _r(high),
                "in_window": k < W // 7,
            })
        return {"alert": public(a), "chart": chart}


def public(alert: dict) -> dict:
    """An alert without the engine's internal fields."""
    return {k: v for k, v in alert.items() if not k.startswith("_")}
