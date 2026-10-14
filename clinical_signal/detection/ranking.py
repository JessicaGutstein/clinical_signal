"""Orders alerts and decides which ones are high priority."""

from __future__ import annotations

import config


def priority_score(excess: float, n_fired: int) -> float:
    """Excess admissions, raised when several comparisons agree.

    An alert that is high against last year, last month, and last week is more
    trustworthy than one that tripped a single test, so each extra comparison
    adds a fixed share to the score.
    """
    return excess * (1.0 + config.AGREEMENT_BONUS * max(n_fired - 1, 0))


def rank(alerts: list[dict]) -> list[dict]:
    """Sort by score, break ties on excess spend, and mark the top N as high priority."""
    for a in alerts:
        a["score"] = priority_score(a["excess"], a["n_fired"])
    alerts.sort(key=lambda a: (-a["score"], -a["excess_spend"]))
    for i, a in enumerate(alerts, start=1):
        a["rank"] = i
        a["priority"] = "high" if i <= config.TOP_N else "low"
    return alerts
