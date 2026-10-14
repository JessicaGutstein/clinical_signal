"""The four comparisons that decide whether a slice is abnormally high.

Each comparison takes daily admission counts for many slices at once (one row
per slice, one column per day, column 0 being the as-of date) and answers the
same three questions: what did we see, what did we expect, and is the gap bigger
than chance would explain.

    seasonal      last 28 days vs. the same 28 days in prior years
    prior_period  last 28 days vs. the 28 days before, allowing for the rise
                  that past years show is normal at this time of year
    latest_week   latest 7 days vs. the average of the three weeks before
    trend         whether the four weekly counts in the window are climbing,
                  sized as the latest two weeks vs. the two before
"""

from __future__ import annotations

import numpy as np

import config

COMPARISONS = [
    ("seasonal", "Same period in prior years"),
    ("prior_period", "Previous 28 days"),
    ("latest_week", "Latest week vs. prior three weeks"),
    ("trend", "Four-week trend"),
]
LABELS = dict(COMPARISONS)
# What each comparison counts, how many days that covers, and what it is set against.
PERIODS = {
    "seasonal": ("last 28 days", 28, "the same period in prior years"),
    "prior_period": ("last 28 days", 28, "the previous 28 days"),
    "latest_week": ("latest week", 7, "the average of the three weeks before"),
    "trend": ("latest two weeks", 14, "the two weeks before"),
}
YEAR = 364  # 52 whole weeks, so weekdays line up year over year
SEASON_PSEUDO = 20.0  # admissions of "no seasonal effect" mixed in before trusting a slice's own seasonal rise


def window(x: np.ndarray, start: int, length: int) -> np.ndarray:
    """Total admissions in `length` days starting `start` days before the as-of date."""
    return x[..., start:start + length].sum(axis=-1)


def weekly(x: np.ndarray, n_weeks: int) -> np.ndarray:
    """Weekly totals, newest week first."""
    n_weeks = min(n_weeks, x.shape[-1] // 7)
    return x[..., : n_weeks * 7].reshape(*x.shape[:-1], n_weeks, 7).sum(axis=-1)


def growth_factor(total: np.ndarray) -> float:
    """Plan-wide volume change, latest year over the year before.

    Prior-year baselines are scaled by this so that steady membership growth is
    not mistaken for a hotspot.
    """
    if total.shape[-1] < 2 * YEAR:
        return 1.0
    latest, before = window(total, 0, YEAR), window(total, YEAR, YEAR)
    return float(np.clip(latest / before, 0.8, 1.25)) if before > 0 else 1.0


def dispersion(x: np.ndarray) -> np.ndarray:
    """How much noisier each slice's weekly counts are than pure chance (1 = chance).

    Measured from week-to-week changes over the past year, which ignores slow
    seasonal swings and captures only the short-term jitter.
    """
    w = weekly(x, 56)[..., 4:]  # leave the current window out
    if w.shape[-1] < 8:
        return np.ones(x.shape[:-1])
    mean = w.mean(axis=-1)
    jitter = np.diff(w, axis=-1).var(axis=-1) / 2.0
    phi = np.where(mean >= 0.5, jitter / np.maximum(mean, 0.5), 1.0)
    return np.clip(phi, 1.0, 4.0)


def _score(obs, exp, n_ref, phi):
    """Standard deviations above baseline, allowing for noise in the baseline itself.

    Both the current count and the baseline are noisy, so the pooled level of the
    two is used for the variance. This keeps a baseline that happened to be low
    from manufacturing a hotspot.
    """
    pooled = (obs + n_ref * exp) / (n_ref + 1.0)
    sd = np.sqrt(phi * np.maximum(pooled, 0.5) * (1.0 + 1.0 / n_ref))
    return (obs - exp) / sd


def evaluate(x: np.ndarray, min_excess: float, growth: float) -> dict:
    """Run all four comparisons on every row of `x` (shape [slices, days])."""
    W = config.WINDOW_DAYS
    n_days = x.shape[-1]
    phi = dispersion(x)
    out = {"phi": phi}

    current = window(x, 0, W)

    # 1. Seasonal: the same 28 days in each prior year we have, scaled for growth.
    refs = [window(x, YEAR * k, W) * growth ** k for k in (1, 2, 3) if YEAR * k + W <= n_days]
    if refs:
        exp = np.mean(refs, axis=0)
        z = _score(current, exp, len(refs), phi)
    else:
        exp, z = np.full_like(current, np.nan), np.full_like(current, -np.inf)
    out["seasonal"] = _pack(current, exp, current - exp, z, min_excess)

    # 2. Prior period: the 28 days before this window.
    # Some rises happen every year at this point (flu in winter). Past years tell us how
    # much: the same 28 days against the 28 days before them, in each prior year. A rise
    # that past years explain is not counted as unusual; anything beyond it still is.
    # The factor only ever removes a seasonal rise (it is never below 1), and the
    # pseudo-counts keep a slice with little history close to "no seasonal effect".
    exp = window(x, W, W)
    years = [k for k in (1, 2, 3) if YEAR * k + 2 * W <= n_days]
    if years:
        same = sum(window(x, YEAR * k, W) for k in years)
        before = sum(window(x, YEAR * k + W, W) for k in years)
        factor = np.clip((same + SEASON_PSEUDO) / (before + SEASON_PSEUDO), 1.0, 3.0)
    else:
        factor = np.ones_like(exp)
    seasonal_exp = exp * factor
    out["prior_period"] = _pack(current, exp, current - exp, _score(current, seasonal_exp, 1, phi), min_excess)
    out["prior_period"]["fired"] &= (current - seasonal_exp) >= min_excess
    out["prior_period"]["season_factor"] = factor

    # 3. Latest week against the average of the three weeks before it.
    wk = weekly(x, 4)  # newest first
    latest, exp = wk[..., 0], wk[..., 1:4].mean(axis=-1)
    out["latest_week"] = _pack(latest, exp, latest - exp, _score(latest, exp, 3, phi), min_excess)

    # 4. Trend: are the four weekly counts climbing more than chance allows?
    # A linear-contrast test: under "no trend" the window's admissions fall
    # evenly across the four weeks.
    oldest_first = wk[..., ::-1]
    position = np.array([-1.5, -0.5, 0.5, 1.5])
    contrast = (oldest_first * position).sum(axis=-1)
    z = contrast / np.sqrt(1.25 * phi * np.maximum(current, 1.0))
    # Size of the climb: the latest two weeks against the two before them.
    first_half = oldest_first[..., :2].sum(axis=-1)
    second_half = oldest_first[..., 2:].sum(axis=-1)
    out["trend"] = _pack(second_half, first_half, second_half - first_half, z, min_excess)
    out["trend"]["slope"] = contrast / 5.0  # admissions gained per week
    out["weekly4"] = oldest_first

    fired = np.stack([out[k]["fired"] for k, _ in COMPARISONS], axis=-1)
    excess_all = np.stack([out[k]["excess"] for k, _ in COMPARISONS], axis=-1)
    out["n_fired"] = fired.sum(axis=-1)
    out["flagged"] = out["n_fired"] > 0
    # The headline comparison is the seasonal one whenever it fired, because
    # "against this time of year" is the most natural meaning of expected.
    # Otherwise it is the fired comparison with the largest excess.
    largest = np.where(fired, excess_all, -np.inf).argmax(axis=-1)
    out["primary"] = np.where(fired[..., 0], 0, largest)
    return out


def _pack(obs, exp, excess, z, min_excess):
    fired = (z >= config.Z_GATE) & (excess >= min_excess)
    return {"observed": obs, "expected": exp, "excess": excess, "z": z, "fired": fired}


def expected_band(x: np.ndarray, growth: float, phi: float, n_weeks: int = 52):
    """Weekly counts for the last year with the range we would normally expect.

    The expected level for a week is the average of the five weeks centred on the
    same week in each prior year, scaled for growth. The range is two standard
    deviations either side.
    """
    all_weeks = weekly(x, x.shape[-1] // 7)  # newest first
    n_weeks = min(n_weeks, len(all_weeks))
    rows = []
    for k in range(n_weeks):
        refs = []
        for years_back in (1, 2, 3):
            centre = k + 52 * years_back
            if centre + 2 < len(all_weeks):
                refs.append(all_weeks[centre - 2: centre + 3].mean() * growth ** years_back)
        if refs:
            exp = float(np.mean(refs))
            spread = 2.0 * float(np.sqrt(phi * max(exp, 0.5)))
            rows.append((k, float(all_weeks[k]), exp, max(exp - spread, 0.0), exp + spread))
        else:
            rows.append((k, float(all_weeks[k]), None, None, None))
    return rows
