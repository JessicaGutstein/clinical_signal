"""Checks that detection behaves as designed.

Run from the project folder with:

    python -m unittest discover tests -v

The first group tests each rule on small made-up series. The second group runs
the full engine on the synthetic admissions file and checks it against the
planted hotspots in data/planted_hotspots_answer_key.csv.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from clinical_signal import summary  # noqa: E402
from clinical_signal.data_loader import load  # noqa: E402
from clinical_signal.detection import Engine  # noqa: E402
from clinical_signal.detection import comparisons as cmp  # noqa: E402
from clinical_signal.detection.ranking import priority_score  # noqa: E402
from clinical_signal.detection.rollup import group_pairs, wave_minimum  # noqa: E402

DAYS = 800


def steady(per_day: float) -> np.ndarray:
    """A slice with the same number of admissions every day (index 0 = as-of date)."""
    return np.full(DAYS, per_day)


def fired(series: np.ndarray, min_excess: float = 6) -> set:
    result = cmp.evaluate(series[None, :], min_excess, growth=1.0)
    return {key for key, _ in cmp.COMPARISONS if result[key]["fired"][0]}


class ComparisonRules(unittest.TestCase):
    def test_steady_slice_is_quiet(self):
        self.assertEqual(fired(steady(1.0)), set())

    def test_sustained_shift_fires_seasonal_and_prior_period(self):
        x = steady(0.5)
        x[:28] = 1.5  # 42 admissions against 14
        self.assertTrue({"seasonal", "prior_period"} <= fired(x))

    def test_one_week_spike_fires_latest_week(self):
        x = steady(0.5)
        x[:7] = 3.0  # 21 in the latest week against 3.5
        self.assertIn("latest_week", fired(x))

    def test_climbing_weeks_fire_trend(self):
        x = steady(0.3)
        for week, rate in enumerate([4.0, 2.5, 1.2, 0.3]):  # newest week first
            x[week * 7:(week + 1) * 7] = rate
        self.assertIn("trend", fired(x))

    def test_normal_seasonal_peak_does_not_fire_seasonal(self):
        x = steady(1.0)
        for year in (0, 1, 2):  # the same bump every year
            x[cmp.YEAR * year: cmp.YEAR * year + 28] = 3.0
        self.assertNotIn("seasonal", fired(x))

    def test_a_rise_that_happens_every_year_does_not_fire_prior_period(self):
        # The flu ramp: three times the level of the month before, every year.
        x = steady(1.0)
        for year in (0, 1, 2):
            x[cmp.YEAR * year: cmp.YEAR * year + 28] = 3.0
        self.assertEqual(fired(x), set())

    def test_a_rise_beyond_the_seasonal_one_still_fires_prior_period(self):
        x = steady(1.0)
        for year in (1, 2):
            x[cmp.YEAR * year: cmp.YEAR * year + 28] = 1.5  # a modest rise in past years
        x[:28] = 5.0                                         # far more than that this year
        self.assertIn("prior_period", fired(x))

    def test_small_slice_doubling_is_blocked_by_minimum_volume(self):
        x = steady(2 / 28)
        x[:28] = 5 / 28  # 2 a month becomes 5: a big percentage, a tiny volume
        self.assertEqual(fired(x), set())

    def test_growth_scales_the_prior_year_baseline(self):
        x = steady(1.0)
        x[:28] = 1.3  # 30% above last year
        without = cmp.evaluate(x[None, :], 6, growth=1.0)["seasonal"]["excess"][0]
        with_growth = cmp.evaluate(x[None, :], 6, growth=1.2)["seasonal"]["excess"][0]
        self.assertLess(with_growth, without)

    def test_agreement_raises_priority(self):
        self.assertGreater(priority_score(10, 3), priority_score(10, 1))


class RollupRules(unittest.TestCase):
    def setUp(self):
        self.areas = ["Queens"] * 4 + ["Bronx"] * 4
        self.regular = np.ones((8, 5), dtype=bool)

    def test_three_facilities_in_one_area_become_a_wave(self):
        flagged = np.zeros((8, 5), dtype=bool)
        flagged[[0, 1, 2], 3] = True
        groups = group_pairs(flagged, self.areas, self.regular)
        self.assertEqual(groups["wave"], {(3, "Queens"): [0, 1, 2]})
        self.assertEqual(groups["single"], [])

    def test_two_facilities_stay_separate(self):
        flagged = np.zeros((8, 5), dtype=bool)
        flagged[[0, 1], 3] = True
        groups = group_pairs(flagged, self.areas, self.regular)
        self.assertEqual(groups["wave"], {})
        self.assertEqual(groups["single"], [(0, 3), (1, 3)])

    def test_three_facilities_in_different_areas_stay_separate(self):
        flagged = np.zeros((8, 5), dtype=bool)
        flagged[[0, 1, 5], 3] = True
        self.assertEqual(group_pairs(flagged, self.areas, self.regular)["wave"], {})

    def test_three_diagnoses_at_one_facility_roll_up(self):
        flagged = np.zeros((8, 5), dtype=bool)
        flagged[6, [0, 1, 2]] = True
        groups = group_pairs(flagged, self.areas, self.regular)
        self.assertEqual(groups["facility"], {6: [0, 1, 2]})

    def test_pair_in_both_patterns_joins_the_larger_one(self):
        flagged = np.zeros((8, 5), dtype=bool)
        flagged[[0, 1, 2, 3], 4] = True   # a four-hospital wave
        flagged[0, [0, 1]] = True         # hospital 0 also has two other diagnoses
        groups = group_pairs(flagged, self.areas, self.regular)
        self.assertEqual(groups["wave"], {(4, "Queens"): [0, 1, 2, 3]})
        self.assertEqual(groups["facility"], {})
        self.assertEqual(groups["single"], [(0, 0), (0, 1)])

    def test_three_facilities_of_one_system_in_different_areas_become_one_group(self):
        flagged = np.zeros((6, 3), dtype=bool)
        flagged[[0, 2, 4], 1] = True
        out = group_pairs(flagged, ["A", "A", "B", "B", "C", "C"], np.ones((6, 3), dtype=bool), ["S"] * 6)
        self.assertEqual(out["system"], {(1, "S"): [0, 2, 4]})
        self.assertEqual(out["single"], [])

    def test_two_facilities_of_one_system_stay_separate(self):
        flagged = np.zeros((6, 3), dtype=bool)
        flagged[[0, 2], 1] = True
        out = group_pairs(flagged, ["A", "A", "B", "B", "C", "C"], np.ones((6, 3), dtype=bool), ["S"] * 6)
        self.assertEqual(out["system"], {})
        self.assertEqual(out["single"], [(0, 1), (2, 1)])

    def test_independent_facilities_are_never_grouped_as_a_system(self):
        flagged = np.zeros((6, 3), dtype=bool)
        flagged[[0, 2, 4], 1] = True
        out = group_pairs(flagged, ["A", "A", "B", "B", "C", "C"], np.ones((6, 3), dtype=bool), [config.INDEPENDENT] * 6)
        self.assertEqual(out["system"], {})

    def test_nearby_facilities_are_grouped_by_area_before_system(self):
        flagged = np.zeros((6, 3), dtype=bool)
        flagged[[0, 1, 2], 1] = True
        out = group_pairs(flagged, ["A"] * 6, np.ones((6, 3), dtype=bool), ["S"] * 6)
        self.assertEqual(out["wave"], {(1, "A"): [0, 1, 2]})
        self.assertEqual(out["system"], {})

    def test_wave_minimum_scales_with_area_size(self):
        self.assertEqual(wave_minimum(10), 3)
        self.assertEqual(wave_minimum(40), 6)


class SummaryGuardrail(unittest.TestCase):
    FACTS = {"what": "Heart failure", "where": "Maimonides Medical Center", "period": "last 28 days", "window_days": 28}

    def test_accepts_plain_sentences_with_no_new_numbers(self):
        text = "More heart failure admissions than usual at Maimonides Medical Center over the last 28 days."
        self.assertIsNone(summary.check(text, self.FACTS))

    def test_rejects_an_invented_number(self):
        self.assertIn("number", summary.check("Admissions rose 93%.", self.FACTS))

    def test_rejects_a_figure_the_screen_shows_elsewhere(self):
        # Counts and cost are not in the facts, so a summary that brings them in fails.
        self.assertIn("number", summary.check("Admissions reached 29 against 15.", self.FACTS))

    def test_rejects_wording_that_points_at_a_cause(self):
        self.assertIn("cause", summary.check("More admissions than usual, likely due to a flu wave.", self.FACTS))

    def test_rejects_a_list_or_a_long_reply(self):
        self.assertIn("sentences", summary.check("- More admissions\n- At Maimonides", self.FACTS))
        self.assertIn("sentences", summary.check("More admissions than usual. " * 30, self.FACTS))


class PlantedHotspots(unittest.TestCase):
    """The engine against the synthetic data and its answer key."""

    @classmethod
    def setUpClass(cls):
        cls.ds = load()
        cls.engine = Engine(cls.ds)
        cls.det = cls.engine.run("all")
        cls.high = [a for a in cls.det.alerts if a["priority"] == "high"]
        cls.name_to_id = dict(zip(cls.ds.facilities["facility_name"], cls.ds.facilities["facility_id"]))

    def covering(self, facility: str, diagnosis: str | None = None, alerts=None):
        """Alerts that involve this facility (and diagnosis, when given)."""
        fid = self.name_to_id[facility]
        hits = []
        for a in (self.high if alerts is None else alerts):
            if fid not in a["facility_ids"] or a["kind"] == "plan_wide":
                continue
            diagnoses = {a["diagnosis"]} | {m["diagnosis"] for m in a["members"] if m["facility_id"] == fid}
            if diagnosis is None or diagnosis in diagnoses:
                hits.append(a)
        return hits

    def test_h1_falls_just_short_on_real_counts(self):
        # Heart failure at Maimonides was caught when recent days were scaled up for late
        # reports. On real reported counts it sits just under the bar. This is recorded,
        # not hidden: see the evaluation set.
        self.assertFalse(self.covering("Maimonides Medical Center", "Heart failure", alerts=self.det.alerts))
        f, d = self.ds.facility_index(self.name_to_id["Maimonides Medical Center"]), self.ds.diagnoses.index("Heart failure")
        z = max(self.det.pair[k]["z"][f * self.engine.D + d] for k in ("seasonal", "prior_period"))
        self.assertGreater(z, 1.3)
        self.assertLess(z, config.Z_GATE)

    def test_h2_multi_facility_wave_rolls_up_to_one_alert(self):
        waves = [a for a in self.high if a["kind"] == "wave" and a["area"] == "Queens"
                 and a["diagnosis"].startswith("Influenza")]
        self.assertEqual(len(waves), 1)
        self.assertGreaterEqual(len(waves[0]["facility_ids"]), config.ROLLUP_MIN_FACILITIES)

    def test_h3_one_facility_many_diagnoses_rolls_up_to_one_alert(self):
        alerts = self.covering("NYC Health + Hospitals/Kings County")
        self.assertEqual([a["kind"] for a in alerts], ["facility"])
        self.assertEqual(alerts[0]["rank"], 1)

    def test_h4_both_bronx_hospitals_are_caught(self):
        for hospital in ("NYC Health + Hospitals/Lincoln", "BronxCare Hospital Center - Concourse Division"):
            self.assertTrue(self.covering(hospital, "COPD and asthma"), hospital)

    def test_h5_one_week_spike_fires_on_the_short_comparisons(self):
        alerts = self.covering("NYU Langone Hospital - Brooklyn", "Gastrointestinal", alerts=self.det.alerts)
        self.assertTrue(alerts)
        flagged_by = {c["key"] for c in alerts[0]["comparisons"] if c["fired"]}
        self.assertTrue(flagged_by & {"latest_week", "trend"})
        self.assertNotIn("seasonal", flagged_by)

    def test_decoy_with_tiny_volume_is_not_an_alert(self):
        self.assertFalse(self.covering("Mount Sinai Brooklyn", "Hypertension", alerts=self.det.alerts))

    def test_top_list_is_capped_and_led_by_planted_hotspots(self):
        self.assertLessEqual(len(self.high), config.TOP_N)
        ranks = [self.covering("NYC Health + Hospitals/Kings County")[0]["rank"],
                 self.covering("NYC Health + Hospitals/Elmhurst")[0]["rank"],
                 self.covering("NYC Health + Hospitals/Lincoln", "COPD and asthma")[0]["rank"]]
        self.assertEqual(sorted(ranks), [1, 2, 4])

    def test_same_diagnosis_across_one_health_system_is_one_hotspot(self):
        system = [a for a in self.det.alerts if a.get("grouped_by") == "system"]
        self.assertEqual(len(system), 1)
        a = system[0]
        self.assertEqual((a["diagnosis"], a["system"], len(a["facility_ids"])), ("Stroke", "Northwell Health", 3))
        areas = {f["area"] for f in self.det.facilities if f["id"] in a["facility_ids"]}
        self.assertEqual(len(areas), 3)  # three boroughs: only the system links them

    def test_network_status_and_membership_are_labels_only(self):
        statuses = {f["network"] for f in self.det.facilities}
        self.assertEqual(statuses, {"In-network", "In-network, value-based contract", "Out-of-network"})
        self.assertTrue(all(f["area_members"] and f["area_members_year_ago"] for f in self.det.facilities))
        # Detection reads the count cube only: shuffling the labels cannot change it.
        import copy
        other = Engine(self.ds)
        other.fac_rows = copy.deepcopy(other.fac_rows)
        for row in other.fac_rows:
            row["network_status"] = "In-network"
        self.assertEqual([a["id"] for a in other.run("all").alerts], [a["id"] for a in self.det.alerts])

    def test_evaluation_set_scores_as_recorded(self):
        # The evaluation set is scored by scripts/run_evaluation.py. The cases that do not
        # behave as expected are listed here on purpose, so a change in detection that
        # fixes or breaks a case is noticed. They are known limits, not passes.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import run_evaluation
        results, totals = run_evaluation.evaluate()
        self.assertEqual(len(results), 30)
        misses = {r["id"] for r in results if not r["passed"]}
        self.assertEqual(misses, {"H1", "H6", "H7", "H8", "D3", "Y2", "N1", "R4", "R5"})
        self.assertEqual(totals["alerts"], len(self.det.alerts))

    def test_past_hotspot_is_found_when_detection_is_replayed(self):
        then = Engine(load(as_of="2026-03-28")).run("all")
        moses = self.name_to_id["Montefiore Medical Center - Moses Campus"]
        hit = [a for a in then.alerts if moses in a["facility_ids"]
               and "Sepsis" in ({a["diagnosis"]} | {m["diagnosis"] for m in a["members"]})]
        self.assertTrue(hit)
        now = self.covering("Montefiore Medical Center - Moses Campus", "Sepsis", alerts=self.det.alerts)
        self.assertFalse(now, "the March hotspot has resolved and should not alert today")

    def test_detection_is_repeatable(self):
        again = Engine(load()).run("all")
        self.assertEqual([a["id"] for a in again.alerts], [a["id"] for a in self.det.alerts])

    def test_counts_are_the_admissions_actually_reported(self):
        # Nothing is scaled up for late reports: detection runs on the reported counts,
        # and every hospital's 28-day total equals the rows in the admissions file.
        import pandas as pd
        self.assertFalse(config.ADJUST_FOR_REPORTING_LAG)
        self.assertTrue(np.array_equal(self.det.adj, self.det.raw))
        adm = pd.read_csv(config.DATA_DIR / "synthetic_admissions.csv", usecols=["facility_id", "admit_date"], parse_dates=["admit_date"])
        start = pd.Timestamp(self.ds.as_of) - pd.Timedelta(days=config.WINDOW_DAYS - 1)
        per = adm[adm["admit_date"] >= start].groupby("facility_id").size()
        for f in self.det.facilities:
            self.assertEqual(f["display"]["observed"], int(per.get(f["id"], 0)), f["name"])

    def test_every_line_of_business_runs(self):
        for lob in self.ds.lobs:
            det = self.engine.run(lob)
            self.assertEqual(len(det.facilities), 100)

    def _claude_says(self, text: str) -> dict:
        """Run the summary writer with Claude's reply replaced by `text`."""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("the anthropic package is not installed")
        reply = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
        client = mock.Mock()
        client.messages.create.return_value = reply
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
                mock.patch("anthropic.Anthropic", return_value=client):
            return summary.write_summary(self.det.alerts[0])

    def test_claude_summary_is_used_when_it_is_plain_and_adds_no_numbers(self):
        out = self._claude_says("Admissions are higher than usual at this hospital over the last 28 days.")
        self.assertEqual(out["source"], "claude")
        self.assertIn("higher than usual", out["text"])

    def test_claude_draft_that_brings_in_counts_falls_back(self):
        d = self.det.alerts[0]["display"]
        out = self._claude_says(f"Admissions here reached {d['observed']} against {d['expected']}.")
        self.assertEqual(out["source"], "standard")
        self.assertIn("rejected", out["note"])

    def test_claude_draft_that_names_a_cause_falls_back(self):
        out = self._claude_says("Admissions are higher than usual, likely due to an outbreak.")
        self.assertEqual(out["source"], "standard")
        self.assertIn("cause", out["note"])

    def test_claude_draft_written_as_a_list_falls_back(self):
        out = self._claude_says("- Admissions are higher than usual\n- At this hospital")
        self.assertEqual(out["source"], "standard")
        self.assertIn("than usual", out["text"])

    def test_summary_still_works_when_claude_cannot_be_reached(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("the anthropic package is not installed")
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), \
                mock.patch("anthropic.Anthropic", side_effect=RuntimeError("offline")):
            out = summary.write_summary(self.det.alerts[0])
        self.assertEqual(out["source"], "standard")

    def test_standard_summary_states_no_cause_and_no_stray_numbers(self):
        for a in self.det.alerts:
            text = summary.standard_summary(a)
            self.assertIsNone(summary.check(text, summary.facts(a)), text)

    def test_standard_summary_is_plain_and_carries_no_figures(self):
        for a in self.det.alerts:
            text = summary.write_summary(a)["text"]
            self.assertIn("than usual", text)
            d = a["display"]
            for figure in (f"+{d['excess']}", f"{d['observed']} vs", "checks", "$"):
                self.assertNotIn(figure, text)
            self.assertEqual("outpatient care" in text, bool(a["avoidable"]))

    def test_every_admission_has_a_diagnosis_code_inside_its_group(self):
        import pandas as pd
        codes = pd.read_csv(config.DATA_DIR / "icd10_codes.csv")
        self.assertEqual(codes["code"].nunique(), len(codes))
        self.assertEqual(set(codes["diagnosis_group"]), set(self.ds.diagnoses))
        adm = pd.read_csv(config.DATA_DIR / "synthetic_admissions.csv", usecols=["diagnosis_group", "diagnosis_code"])
        group_of = dict(zip(codes["code"], codes["diagnosis_group"]))
        self.assertTrue((adm["diagnosis_code"].map(group_of) == adm["diagnosis_group"]).all())

    def test_code_breakdown_shows_the_leading_code_of_a_planted_hotspot(self):
        wave = next(a for a in self.det.alerts if a["kind"] == "wave" and a["diagnosis"].startswith("Influenza"))
        out = self.engine.code_breakdown("all", wave["facility_ids"], wave["diagnosis"])
        self.assertEqual(out["codes"][0]["code"], "J10.1")
        self.assertGreater(out["codes"][0]["share"], out["codes"][0]["usual_share"])
        self.assertLessEqual(len(out["codes"]), config.TOP_CODES)
        self.assertEqual(sum(c["count"] for c in out["codes"]), out["reported"])  # five codes or fewer in play here
        self.assertAlmostEqual(sum(c["usual_share"] for c in out["codes"]), 1.0, delta=0.4)

    def test_code_breakdown_borrows_plan_wide_mix_when_history_is_thin(self):
        thin = self.engine.code_breakdown("all", ["F096"], "Sepsis")
        self.assertEqual(thin["usual_basis"], "plan")
        everyone = self.engine.code_breakdown("all", None, "Sepsis")
        self.assertEqual(everyone["usual_basis"], "own")
        self.assertEqual(everyone["n_facilities"], 100)

    def test_code_breakdown_covers_several_groups_or_all_of_them(self):
        # A hotspot that spans diagnosis groups gets one list across them.
        hospital = next(a for a in self.det.alerts if a["kind"] == "facility")
        fid = hospital["facility_ids"]
        everything = self.engine.code_breakdown("all", fid, None)
        self.assertTrue(everything["all_groups"])
        self.assertEqual(everything["n_groups"], len(self.ds.diagnoses))
        self.assertIsNone(everything["diagnosis"])
        self.assertLessEqual(len(everything["codes"]), config.TOP_CODES)
        counts = [c["count"] for c in everything["codes"]]
        self.assertEqual(counts, sorted(counts, reverse=True))
        # Every admission in the window sits in exactly one group, so the parts add up.
        parts = [self.engine.code_breakdown("all", fid, g)["reported"] for g in self.ds.diagnoses]
        self.assertEqual(sum(parts), everything["reported"])
        two = self.ds.diagnoses[:2]
        pair = self.engine.code_breakdown("all", fid, two)
        self.assertEqual(pair["n_groups"], 2)
        self.assertFalse(pair["all_groups"])
        self.assertEqual(pair["reported"], parts[0] + parts[1])
        self.assertTrue(all(c["group"] in two for c in pair["codes"]))

    def test_codes_endpoint_accepts_one_group_several_or_all(self):
        from clinical_signal import create_app
        client = create_app().test_client()
        one = client.get("/api/codes", query_string={"diagnosis": "Sepsis", "facilities": "all"})
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.get_json()["diagnosis"], "Sepsis")
        several = client.get("/api/codes?diagnosis=Sepsis&diagnosis=Stroke&facilities=F047")
        self.assertEqual(several.get_json()["n_groups"], 2)
        everything = client.get("/api/codes?diagnosis=all&facilities=F047")
        self.assertTrue(everything.get_json()["all_groups"])
        self.assertEqual(client.get("/api/codes?diagnosis=Nonsense&facilities=all").status_code, 400)
        self.assertEqual(client.get("/api/codes?facilities=all").status_code, 400)
        self.assertEqual(client.get("/api/codes?diagnosis=all&facilities=F999").status_code, 400)

    def test_codes_never_change_what_is_flagged(self):
        # Detection reads only the count cube; the code tables are separate arrays.
        self.assertEqual(self.ds.code_window.shape[:2], self.ds.counts.shape[:2])
        self.assertEqual(len(self.det.alerts), 28)

    def test_facility_totals_always_describe_the_28_day_window(self):
        window = self.det.adj[:, :, :28].sum(axis=(1, 2))
        for f, row in enumerate(self.det.facilities):
            self.assertAlmostEqual(row["observed"], round(float(window[f]), 1), places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
