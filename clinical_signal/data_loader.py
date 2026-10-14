"""Loads the admissions file and turns it into daily counts.

The output is a small cube of counts indexed by line of business, facility,
diagnosis group, and age in days (0 is the as-of date). Everything downstream
works on that cube, so the 170,000-row file is read only once at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import config

ADMISSIONS_FILE = "synthetic_admissions.csv"
FACILITIES_FILE = "facilities.csv"
CODES_FILE = "icd10_codes.csv"
MEMBERSHIP_FILE = "membership_by_area.csv"


@dataclass
class Dataset:
    as_of: date
    facilities: pd.DataFrame       # one row per facility, in cube order
    diagnoses: list[str]           # diagnosis groups, in cube order
    avoidable: dict[str, bool]     # diagnosis group -> potentially avoidable
    lobs: list[str]                # lines of business, in cube order
    counts: np.ndarray             # [lob, facility, diagnosis, age] reported admissions
    completeness: np.ndarray       # [age] share of admissions reported by that age
    avg_paid: np.ndarray           # [facility, diagnosis] average paid per admission
    n_days: int
    # ICD-10 codes describe what is inside a slice. They play no part in detection.
    codes: pd.DataFrame            # one row per code: code, diagnosis_group, name, meaning
    code_window: np.ndarray        # [lob, facility, code] admissions reported in the detection window
    code_prior: np.ndarray         # [lob, facility, code] admissions in the year before the window
    preliminary: np.ndarray        # [lob, facility, diagnosis] window admissions still without a claim
    # Members living in each area, now and a year ago. Context only: detection counts admissions.
    membership: dict               # area -> {"members": n, "year_ago": n}

    def facility_index(self, facility_id: str) -> int:
        return int(self.facilities.index[self.facilities["facility_id"] == facility_id][0])


def load(data_dir: Path | None = None, as_of: str | date | None = None) -> Dataset:
    data_dir = Path(data_dir or config.DATA_DIR)
    facilities = pd.read_csv(data_dir / FACILITIES_FILE)
    # Rollups group hospitals by area: the borough in the city, the county outside it.
    county = facilities["county"].str.replace(r"^(.*) \(NJ\)$", r"\1 County, NJ", regex=True)
    county = county.where(county.str.contains("County"), county + " County")
    facilities["area"] = np.where(facilities["borough"] == "Outside NYC", county, facilities["borough"])

    df = pd.read_csv(
        data_dir / ADMISSIONS_FILE,
        usecols=[
            "facility_id", "line_of_business", "admit_date",
            "admitting_diagnosis_group", "final_diagnosis_group", "potentially_avoidable",
            "diagnosis_group", "diagnosis_code", "notification_date", "claim_received_date", "paid_amount",
        ],
        parse_dates=["admit_date", "notification_date", "claim_received_date"],
    )

    as_of_ts = pd.Timestamp(as_of or config.AS_OF or df["admit_date"].max()).normalize()

    # Avoidable flags come from the file's own best-available diagnosis column.
    avoidable = (
        df.groupby("diagnosis_group")["potentially_avoidable"].first().eq("Y").to_dict()
    )

    # Keep only what the plan would have known on the as-of date: an admission is
    # visible once a notification or a claim for it has arrived.
    notified = df["notification_date"].le(as_of_ts)
    claimed = df["claim_received_date"].le(as_of_ts)
    df = df[(notified | claimed) & df["admit_date"].le(as_of_ts)].copy()
    claimed = df["claim_received_date"].le(as_of_ts).to_numpy()
    df["age"] = (as_of_ts - df["admit_date"]).dt.days

    diagnoses = sorted(avoidable)
    lobs = sorted(df["line_of_business"].unique())
    fac_ids = list(facilities["facility_id"])
    n_days = int(df["age"].max()) + 1

    li = pd.Categorical(df["line_of_business"], categories=lobs).codes
    fi = pd.Categorical(df["facility_id"], categories=fac_ids).codes
    admitting = pd.Categorical(df["admitting_diagnosis_group"], categories=diagnoses).codes
    final = pd.Categorical(df["final_diagnosis_group"], categories=diagnoses).codes
    age = df["age"].to_numpy()
    shape = (len(lobs), len(fac_ids), len(diagnoses), n_days)

    # Admissions with a claim are counted under their final diagnosis.
    counts = np.zeros(shape, dtype=np.float64)
    np.add.at(counts, (li[claimed], fi[claimed], final[claimed], age[claimed]), 1.0)

    # Admissions without a claim yet only have a preliminary diagnosis. By default
    # each one is counted once, under that diagnosis, so every count is a whole
    # number of reported admissions. With REWEIGHT_PRELIMINARY on, each is instead
    # spread across diagnosis groups in the proportions that preliminary diagnosis
    # has turned into in the past.
    pending = np.zeros(shape, dtype=np.float64)
    np.add.at(pending, (li[~claimed], fi[~claimed], admitting[~claimed], age[~claimed]), 1.0)
    if config.REWEIGHT_PRELIMINARY:
        pending = np.einsum("lfat,ad->lfdt", pending, _reclassification(admitting[claimed], final[claimed], len(diagnoses)))
    counts += pending

    codes = pd.read_csv(data_dir / CODES_FILE, usecols=["code", "diagnosis_group", "name", "meaning"])
    code_window, code_prior, preliminary = _code_counts(df, codes, li, fi, age, claimed, diagnoses, len(lobs), len(fac_ids))

    completeness = _completeness_curve(df, as_of_ts, n_days)
    members = pd.read_csv(data_dir / MEMBERSHIP_FILE)
    membership = {r["area"]: {"members": int(r["members"]), "year_ago": int(r["members_year_ago"])} for _, r in members.iterrows()}
    avg_paid = _average_paid(df[claimed], fi[claimed], final[claimed], len(fac_ids), len(diagnoses))

    return Dataset(
        as_of=as_of_ts.date(), facilities=facilities, diagnoses=diagnoses,
        avoidable={d: bool(avoidable[d]) for d in diagnoses}, lobs=lobs, counts=counts,
        completeness=completeness, avg_paid=avg_paid, n_days=n_days,
        codes=codes, code_window=code_window, code_prior=code_prior, preliminary=preliminary,
        membership=membership,
    )


def _code_counts(df, codes, li, fi, age, claimed, diagnoses, n_lob, n_fac):
    """Admissions by ICD-10 code: in the detection window, and in the year before it.

    These are plain counts of reported admissions under their best-available
    diagnosis, so they describe a slice without being adjusted or re-weighted.
    """
    ci = pd.Categorical(df["diagnosis_code"], categories=list(codes["code"])).codes
    known = ci >= 0
    window = np.zeros((n_lob, n_fac, len(codes)))
    prior = np.zeros_like(window)
    in_window = known & (age < config.WINDOW_DAYS)
    in_prior = known & (age >= config.WINDOW_DAYS) & (age < config.WINDOW_DAYS + 364)
    np.add.at(window, (li[in_window], fi[in_window], ci[in_window]), 1.0)
    np.add.at(prior, (li[in_prior], fi[in_prior], ci[in_prior]), 1.0)

    best = pd.Categorical(df["diagnosis_group"], categories=diagnoses).codes
    waiting = (~claimed) & (age < config.WINDOW_DAYS) & (best >= 0)
    preliminary = np.zeros((n_lob, n_fac, len(diagnoses)))
    np.add.at(preliminary, (li[waiting], fi[waiting], best[waiting]), 1.0)
    return window, prior, preliminary


def _reclassification(admitting: np.ndarray, final: np.ndarray, n_dx: int) -> np.ndarray:
    """P(final diagnosis | preliminary diagnosis), learned from admissions with a claim."""
    seen = np.zeros((n_dx, n_dx))
    np.add.at(seen, (admitting, final), 1.0)
    totals = seen.sum(axis=1, keepdims=True)
    return np.where(totals > 0, seen / np.maximum(totals, 1.0), np.eye(n_dx))


def _completeness_curve(df: pd.DataFrame, as_of_ts: pd.Timestamp, n_days: int) -> np.ndarray:
    """Share of admissions the plan has heard about, by days since admission.

    Learned from mature history: for admissions old enough to be fully reported,
    how many days passed before the first notification or claim arrived.
    """
    horizon = config.COMPLETENESS_HORIZON_DAYS
    mature = df[(df["age"] >= horizon) & (df["age"] < horizon + 365)]
    first_seen = mature[["notification_date", "claim_received_date"]].min(axis=1)
    lag = (first_seen - mature["admit_date"]).dt.days.clip(lower=0).to_numpy()
    curve = np.ones(n_days)
    if len(lag):
        hist = np.bincount(np.minimum(lag, horizon), minlength=horizon + 1)
        cdf = np.cumsum(hist) / hist.sum()
        curve[:horizon] = cdf[:horizon]
    return np.clip(curve, config.COMPLETENESS_FLOOR, 1.0)


def _average_paid(paid: pd.DataFrame, fi: np.ndarray, di: np.ndarray, n_f: int, n_d: int) -> np.ndarray:
    """Average paid amount per admission for each facility x diagnosis, last 12 months.

    Thin slices fall back to the diagnosis-wide average so one costly case cannot
    set the price for a whole slice.
    """
    recent = (paid["age"] < 365).to_numpy()
    amount = paid["paid_amount"].to_numpy()[recent]
    total = np.zeros((n_f, n_d))
    n = np.zeros((n_f, n_d))
    np.add.at(total, (fi[recent], di[recent]), amount)
    np.add.at(n, (fi[recent], di[recent]), 1.0)
    dx_avg = total.sum(0) / np.maximum(n.sum(0), 1.0)
    overall = total.sum() / max(n.sum(), 1.0)
    dx_avg = np.where(n.sum(0) > 0, dx_avg, overall)
    return np.where(n >= 10, total / np.maximum(n, 1.0), dx_avg[None, :])
