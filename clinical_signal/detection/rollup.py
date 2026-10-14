"""Groups flagged facility x diagnosis pairs so one real event is one alert.

Two patterns get rolled up:

    facility   one facility flagged for several diagnosis groups at once,
               which points at the facility itself
    wave       the same diagnosis flagged at several facilities in one area,
               which points at something broader than any one hospital
    system     the same diagnosis flagged at several facilities of one health
               system that an area did not already group, which points at the
               system the plan contracts with

Anything left over stays as its own facility x diagnosis alert.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

import config


def wave_minimum(n_regular_facilities: int) -> int:
    """Facilities needed before a diagnosis is treated as an area-wide wave."""
    return max(config.ROLLUP_MIN_FACILITIES,
               math.ceil(config.ROLLUP_MIN_SHARE * n_regular_facilities))


def group_pairs(flagged: np.ndarray, areas: list[str], regular: np.ndarray, systems: list[str] | None = None) -> dict:
    """Split flagged pairs into facility rollups, waves, and single alerts.

    flagged  [facility, diagnosis] True where the pair passed the gate
    areas    area name for each facility
    regular  [facility, diagnosis] True where the facility regularly admits it
    """
    pairs = {(int(f), int(d)) for f, d in zip(*np.nonzero(flagged))}
    grouped_systems = systems is not None

    def area_minimum(d: int, area: str) -> int:
        in_area = [i for i, a in enumerate(areas) if a == area]
        return wave_minimum(int(regular[in_area, d].sum()))

    # Candidate groups, before deciding who belongs where.
    by_facility, by_dx_area, by_dx_system = defaultdict(set), defaultdict(set), defaultdict(set)
    for f, d in pairs:
        by_facility[f].add(d)
        by_dx_area[(d, areas[f])].add(f)
        if grouped_systems and systems[f] != config.INDEPENDENT:
            by_dx_system[(d, systems[f])].add(f)
    facility_groups = {f: ds for f, ds in by_facility.items() if len(ds) >= config.ROLLUP_MIN_DIAGNOSES}
    waves = {k: fs for k, fs in by_dx_area.items() if len(fs) >= area_minimum(*k)}
    system_waves = {k: fs for k, fs in by_dx_system.items() if len(fs) >= config.ROLLUP_MIN_FACILITIES}

    # A pair can fit more than one pattern. It goes with the pattern that has more
    # members, because that is the better explanation. Ties are settled in a fixed
    # order: nearby facilities first, then the health system, then the single facility.
    for f, d in sorted(pairs):
        options = []
        if (d, areas[f]) in waves:
            options.append((len(waves[(d, areas[f])]), 2, "area"))
        if grouped_systems and (d, systems[f]) in system_waves:
            options.append((len(system_waves[(d, systems[f])]), 1, "system"))
        if f in facility_groups:
            options.append((len(facility_groups[f]), 0, "facility"))
        if len(options) < 2:
            continue
        keep = max(options)[2]
        if keep != "area" and (d, areas[f]) in waves:
            waves[(d, areas[f])].discard(f)
        if keep != "system" and grouped_systems and (d, systems[f]) in system_waves:
            system_waves[(d, systems[f])].discard(f)
        if keep != "facility" and f in facility_groups:
            facility_groups[f].discard(d)

    # A group that lost members and fell below its minimum dissolves.
    facility_groups = {f: sorted(ds) for f, ds in facility_groups.items() if len(ds) >= config.ROLLUP_MIN_DIAGNOSES}
    kept_waves = {k: sorted(fs) for k, fs in waves.items() if len(fs) >= area_minimum(*k)}
    system_waves = {k: sorted(fs) for k, fs in system_waves.items() if len(fs) >= config.ROLLUP_MIN_FACILITIES}

    grouped = {(f, d) for f, ds in facility_groups.items() for d in ds}
    grouped |= {(f, d) for (d, _), fs in kept_waves.items() for f in fs}
    grouped |= {(f, d) for (d, _), fs in system_waves.items() for f in fs}
    return {"facility": facility_groups, "wave": kept_waves, "system": system_waves, "single": sorted(pairs - grouped)}
