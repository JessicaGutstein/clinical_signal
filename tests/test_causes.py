"""Checks part two: what may be driving a hotspot.

Run from the project folder with:

    python -m unittest tests.test_causes -v

The first group tests each matching rule on small made-up items. The second runs
the rules on today's real hotspots and compares them with
data/outside_signals_answer_key.csv. The third checks what Claude is and is not
allowed to write, and the last checks that a person's decisions are saved.
"""

from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from clinical_signal import causes, create_app  # noqa: E402
from clinical_signal.reviews import Reviews  # noqa: E402

AS_OF = date(2026, 10, 3)
RISE = date(2026, 9, 6)  # first day of a 28-day hotspot
FACILITIES = [
    {"id": "FA", "type": "Acute care hospital", "area": "Queens", "system": "Test Health System"},
    {"id": "FB", "type": "Children's hospital", "area": "Queens", "system": "Independent"},
    {"id": "FC", "type": "Acute care hospital", "area": "Bronx", "system": "Independent"},
]


def hotspot(kind="pair", fids=("FA",), dx="COPD and asthma", **more) -> dict:
    return {"id": "t", "kind": kind, "title": dx or "All admissions", "subtitle": "somewhere", "facility_ids": list(fids),
            "diagnosis": dx, "period": "last 28 days", "area": "Queens", "members": [], **more}


def outside(starts="2026-09-04", **more) -> dict:
    base = {"id": "X1", "source_type": "news", "source_name": "Test Wire", "published": date.fromisoformat(starts),
            "starts": date.fromisoformat(starts), "ends": None, "areas": ["Queens"], "facility_ids": [], "system": "",
            "topic": "air_quality", "direct": ["COPD and asthma"], "indirect": [], "population": "all", "level": "notable",
            "title": "A test item", "body": "Text of the item."}
    base.update(more)
    if isinstance(base["ends"], str):
        base["ends"] = date.fromisoformat(base["ends"])
    return base


def run(alert, *items):
    return causes.shortlist(alert, FACILITIES, AS_OF, list(items))


class MatchingRules(unittest.TestCase):
    def test_an_item_that_names_the_facility_and_fits_is_strong(self):
        r = run(hotspot(), outside(facility_ids=["FA"]))
        self.assertEqual([(c["strength"], c["score"]) for c in r["causes"]], [("strong", 7)])

    def test_an_area_item_for_one_facility_scores_lower_on_place(self):
        c = run(hotspot(), outside())["causes"][0]
        self.assertEqual((c["score"], c["strength"]), (6, "strong"))
        self.assertEqual(c["parts"][0]["points"], 2)

    def test_a_regionwide_item_with_an_indirect_link_is_weak(self):
        c = run(hotspot(), outside(areas=["All"], direct=[], indirect=["COPD and asthma"]))["causes"][0]
        self.assertEqual((c["score"], c["strength"]), (4, "weak"))

    def test_an_item_somewhere_else_is_set_aside_not_offered(self):
        r = run(hotspot(), outside(areas=["Bronx"]))
        self.assertEqual(r["causes"], [])
        self.assertIn("different place", r["set_aside"][0]["reason"])

    def test_an_item_about_another_diagnosis_is_not_even_listed(self):
        r = run(hotspot(), outside(direct=["Stroke"]))
        self.assertEqual((r["causes"], r["set_aside"]), ([], []))

    def test_an_item_that_ended_long_before_the_rise_is_set_aside(self):
        r = run(hotspot(), outside(starts="2026-06-20", ends="2026-07-25"))
        self.assertEqual(r["causes"], [])
        self.assertIn("ended", r["set_aside"][0]["reason"])

    def test_an_item_that_began_after_the_rise_cannot_be_its_cause(self):
        r = run(hotspot(), outside(starts="2026-09-28"))
        self.assertEqual(r["causes"], [])
        self.assertIn("after the rise started", r["set_aside"][0]["reason"])

    def test_an_item_dated_in_the_future_is_set_aside(self):
        r = run(hotspot(), outside(starts="2026-11-10"))
        self.assertIn("not happened yet", r["set_aside"][0]["reason"])

    def test_an_old_ongoing_change_is_set_aside(self):
        r = run(hotspot(), outside(starts="2025-12-01"))
        self.assertIn("too long ago", r["set_aside"][0]["reason"])

    def test_an_early_but_possible_item_loses_a_timing_point(self):
        c = run(hotspot(), outside(starts="2026-08-10"))["causes"][0]
        self.assertEqual((c["parts"][1]["points"], c["strength"]), (1, "moderate"))

    def test_a_routine_bulletin_is_never_a_cause(self):
        r = run(hotspot(), outside(level="routine"))
        self.assertEqual(r["causes"], [])
        self.assertIn("nothing unusual", r["set_aside"][0]["reason"])

    def test_an_undated_trend_story_is_never_more_than_weak(self):
        c = run(hotspot(), outside(level="background", facility_ids=["FA"]))["causes"][0]
        self.assertEqual(c["strength"], "weak")

    def test_a_childrens_item_fits_a_childrens_hospital_and_not_another(self):
        item = outside(population="children")
        self.assertEqual(run(hotspot(fids=("FB",)), item)["causes"][0]["strength"], "strong")
        self.assertEqual(run(hotspot(fids=("FA",)), item)["causes"][0]["strength"], "weak")

    def test_an_item_about_every_admission_fits_a_whole_facility_better_than_one_diagnosis(self):
        item = outside(direct=["All"], facility_ids=["FA"], topic="facility_closure")
        whole = run(hotspot(kind="facility_wide", dx=None), item)["causes"][0]
        one = run(hotspot(), item)["causes"][0]
        self.assertGreater(whole["score"], one["score"])

    def test_a_health_system_item_fits_a_system_wide_hotspot(self):
        alert = hotspot(kind="wave", fids=("FA", "FC"), dx="Stroke", grouped_by="system", system="Test Health System", area=None)
        c = run(alert, outside(areas=[], system="Test Health System", direct=["Stroke"], topic="routing_change"))["causes"][0]
        self.assertEqual((c["parts"][0]["points"], c["strength"]), (3, "strong"))

    def test_items_on_one_topic_become_one_cause(self):
        r = run(hotspot(), outside(), outside(id="X2", source_type="weather_air", starts="2026-09-10"))
        self.assertEqual(len(r["causes"]), 1)
        self.assertEqual((r["causes"][0]["n_items"], r["causes"][0]["n_source_types"]), (2, 2))

    def test_at_most_three_causes_are_offered_best_first(self):
        topics = ["air_quality", "heat", "care_access", "outbreak"]
        items = [outside(id=f"X{i}", topic=t, facility_ids=["FA"] if i == 2 else []) for i, t in enumerate(topics)]
        r = run(hotspot(), *items)
        self.assertEqual(len(r["causes"]), 3)
        self.assertEqual(r["causes"][0]["topic"], "care_access")
        self.assertIn("fit better", r["set_aside"][0]["reason"])

    def test_a_two_week_hotspot_is_timed_from_its_own_start(self):
        self.assertEqual(causes.window_start(hotspot(period="latest two weeks"), AS_OF), date(2026, 9, 20))
        self.assertEqual(causes.window_start(hotspot(), AS_OF), RISE)

    def test_the_same_inputs_always_give_the_same_answer(self):
        items = [outside(), outside(id="X2", topic="heat", areas=["All"], direct=[], indirect=["COPD and asthma"])]
        self.assertEqual(json.dumps(run(hotspot(), *items), sort_keys=True), json.dumps(run(hotspot(), *items), sort_keys=True))


def reply(payload) -> SimpleNamespace:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    client = mock.Mock()
    client.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])
    return client


class ClaudeGuardrail(unittest.TestCase):
    """What Claude writes is checked before it is shown. Anything that fails falls back to standard wording."""

    def setUp(self):
        self.alert = hotspot()
        self.result = causes.shortlist(self.alert, FACILITIES, AS_OF, [outside()])
        self.standard = self.result["causes"][0]["why"]

    def explain(self, payload):
        fake = mock.Mock()
        fake.Anthropic.return_value = reply(payload)
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test"}), mock.patch.dict(sys.modules, {"anthropic": fake}):
            return causes.explain(self.alert, self.result)

    def draft(self, **changes):
        d = {"topic": "air_quality", "label": "Poor air in Queens", "why": "Dirty air may be setting off asthma attacks.",
             "cites": ["X1"], "strength": "strong"}
        d.update(changes)
        return {"causes": [d]}

    def test_a_hedged_explanation_that_cites_its_items_is_used(self):
        c = self.explain(self.draft())["causes"][0]
        self.assertEqual((c["written_by"], c["label"]), ("claude", "Poor air in Queens"))

    def test_claude_only_sees_the_shortlisted_items(self):
        given = json.dumps(causes.facts(self.alert, self.result))
        self.assertIn("X1", given)
        self.assertNotIn("excess", given)

    def test_a_cause_stated_as_fact_falls_back(self):
        out = self.explain(self.draft(why="The rise is caused by dirty air."))
        self.assertEqual((out["causes"][0]["written_by"], out["causes"][0]["why"]), ("standard", self.standard))
        self.assertIn("stated a cause as fact", out["note"])

    def test_an_explanation_with_no_could_or_may_falls_back(self):
        self.assertEqual(self.explain(self.draft(why="Dirty air sets off asthma attacks."))["causes"][0]["written_by"], "standard")

    def test_a_cause_that_cites_nothing_or_something_else_falls_back(self):
        self.assertEqual(self.explain(self.draft(cites=[]))["causes"][0]["written_by"], "standard")
        self.assertEqual(self.explain(self.draft(cites=["S999"]))["causes"][0]["written_by"], "standard")

    def test_an_invented_number_falls_back(self):
        self.assertEqual(self.explain(self.draft(why="This may explain 40 admissions."))["causes"][0]["written_by"], "standard")

    def test_claude_may_lower_a_rating(self):
        c = self.explain(self.draft(strength="weak"))["causes"][0]
        self.assertEqual((c["strength"], c["rule_strength"], c.get("lowered_by_ai")), ("weak", "strong", True))

    def test_claude_may_never_raise_a_rating(self):
        self.result = causes.shortlist(self.alert, FACILITIES, AS_OF, [outside(areas=["All"], direct=[], indirect=["COPD and asthma"])])
        c = self.explain(self.draft(strength="strong"))["causes"][0]
        self.assertEqual((c["strength"], c["written_by"]), ("weak", "standard"))

    def test_a_cause_claude_invents_is_ignored(self):
        payload = self.draft()
        payload["causes"].append({"topic": "made_up", "label": "Something else", "why": "It may be this.", "cites": ["X1"], "strength": "strong"})
        self.assertEqual([c["topic"] for c in self.explain(payload)["causes"]], ["air_quality"])

    def test_a_reply_that_is_not_json_falls_back(self):
        out = self.explain("I think it is the air.")
        self.assertEqual((out["writer"], out["causes"][0]["why"]), ("standard", self.standard))

    def test_without_a_key_the_standard_wording_is_used_and_says_so(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            out = causes.explain(self.alert, self.result)
        self.assertEqual(out["writer"], "standard")
        self.assertIn("standard wording", out["note"])

    def test_every_standard_explanation_is_hedged_and_states_no_fact(self):
        for topic, (label, why) in causes.TOPICS.items():
            self.assertRegex(why, causes.HEDGE, topic)
            self.assertIsNone(causes.DEFINITE.search(f"{label} {why}"), topic)


class TodaysHotspots(unittest.TestCase):
    """The rules on the real hotspots, against the answer key. Claude is switched off."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with mock.patch.dict(os.environ, {}, clear=True):
            cls.app = create_app(reviews_path=Path(cls.tmp.name) / "reviews.json")
        cls.client = cls.app.test_client()
        cls.engine = cls.app.extensions["engine"]
        cls.alerts = cls.engine.run("all").alerts
        with open(config.DATA_DIR / "outside_signals_answer_key.csv", newline="", encoding="utf-8") as f:
            cls.key = {r["hotspot_id"]: r for r in csv.DictReader(f)}
        cls.patch = mock.patch.dict(os.environ, {}, clear=True)
        cls.patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.tmp.cleanup()

    def causes_for(self, alert_id):
        return self.client.get(f"/api/alerts/{alert_id}/causes").get_json()

    def test_every_outside_item_has_a_page_that_says_it_is_made_up(self):
        import html as _html
        items = self.app.extensions["outside"]
        articles = config.EXTERNAL_DIR / "articles"
        self.assertEqual({p.stem for p in articles.glob("*.html")}, {i["id"] for i in items})
        names = set(self.engine.ds.facilities["facility_name"]) | set(self.engine.ds.facilities["health_system"]) - {config.INDEPENDENT}
        for i in items:
            page = (articles / f"{i['id']}.html").read_text(encoding="utf-8")
            self.assertIn("Made up for the Clinical Signal prototype", page, i["id"])
            self.assertIn(_html.escape(i["title"]), page, i["id"])
            self.assertIn(_html.escape(i["body"]), page, i["id"])
            for name in names:  # no page may name a real hospital or health system
                self.assertNotIn(name, page, f"{i['id']} names {name}")

    def test_an_item_links_to_its_page_and_the_page_opens(self):
        alert = next(a for a in self.alerts if self.causes_for(a["id"])["causes"])
        item = self.causes_for(alert["id"])["causes"][0]["items"][0]
        self.assertEqual(item["url"], f"/external/articles/{item['id']}.html")
        got = self.client.get(item["url"])
        self.assertEqual(got.status_code, 200)
        self.assertIn(item["title"].split(";")[0][:20], got.get_data(as_text=True))
        self.assertEqual(self.client.get("/external/").status_code, 200)
        self.assertEqual(self.client.get("/external/articles/S999.html").status_code, 404)
        self.assertEqual(self.client.get("/external/articles/..%2Foutside_signals.html").status_code, 404)

    def test_the_outside_file_is_separate_and_marked_as_invented(self):
        items = self.app.extensions["outside"]
        self.assertGreater(len(items), 150)
        self.assertEqual({i["source_type"] for i in items}, set(causes.SOURCE_TYPES))
        admissions = (config.DATA_DIR / "synthetic_admissions.csv").read_text(encoding="utf-8")[:2000]
        self.assertNotIn("item_id", admissions)

    def test_the_answer_key_covers_exactly_todays_hotspots(self):
        self.assertEqual(set(self.key), {a["id"] for a in self.alerts})

    def test_every_hotspot_gets_the_cause_the_answer_key_expects(self):
        wrong = []
        for a in self.alerts:
            found = self.causes_for(a["id"])["causes"]
            got = (found[0]["topic"], found[0]["strength"]) if found else ("none", "none")
            want = (self.key[a["id"]]["expected_top_topic"], self.key[a["id"]]["expected_strength"])
            if got != want:
                wrong.append(f"{a['id']}: got {got}, expected {want}")
        self.assertEqual(wrong, [])

    def test_no_chance_hotspot_gets_a_strong_or_moderate_cause(self):
        for a in self.alerts:
            if self.key[a["id"]]["planted"] == "No":
                self.assertTrue(all(c["strength"] == "weak" for c in self.causes_for(a["id"])["causes"]), a["id"])

    def test_some_hotspots_honestly_have_no_outside_explanation(self):
        empty = [a["id"] for a in self.alerts if not self.causes_for(a["id"])["causes"]]
        self.assertGreaterEqual(len(empty), 5)

    def test_every_cause_shows_the_items_behind_it(self):
        for a in self.alerts:
            for c in self.causes_for(a["id"])["causes"]:
                self.assertTrue(c["items"] and all(i["title"] and i["body"] and i["source_name"] for i in c["items"]))
                self.assertEqual([p["test"] for p in c["parts"]][:3], ["Place", "Timing", "Diagnosis"])

    def test_outside_items_never_change_what_is_detected(self):
        before = [(a["id"], a["rank"], round(a["excess"], 3)) for a in self.alerts]
        for a in self.alerts:
            self.causes_for(a["id"])
        after = [(a["id"], a["rank"], round(a["excess"], 3)) for a in self.engine.run("all").alerts]
        self.assertEqual(before, after)

    def test_a_decision_is_saved_shown_and_can_be_cleared(self):
        url = "/api/alerts/wave-0-Bronx/causes/air_quality/review"
        saved = self.client.post(url, json={"decision": "confirmed", "reviewer": "Test Analyst", "note": "Dates line up."}).get_json()
        self.assertEqual((saved["review"]["decision"], saved["review"]["reviewer"]), ("confirmed", "Test Analyst"))
        again = self.causes_for("wave-0-Bronx")
        self.assertEqual(again["confirmed"], [again["causes"][0]["label"]])
        self.assertTrue(json.loads((Path(self.tmp.name) / "reviews.json").read_text()))
        self.assertIsNone(self.client.post(url, json={"decision": None}).get_json()["review"])
        self.assertEqual(self.causes_for("wave-0-Bronx")["confirmed"], [])

    def test_a_bad_decision_or_an_unknown_cause_is_refused(self):
        self.assertEqual(self.client.post("/api/alerts/wave-0-Bronx/causes/air_quality/review", json={"decision": "maybe"}).status_code, 400)
        self.assertEqual(self.client.post("/api/alerts/wave-0-Bronx/causes/heat/review", json={"decision": "confirmed"}).status_code, 404)
        self.assertEqual(self.client.get("/api/alerts/no-such-alert/causes").status_code, 404)

    def test_nothing_is_confirmed_until_a_person_confirms_it(self):
        for a in self.alerts:
            if a["id"] != "wave-0-Bronx":
                found = self.causes_for(a["id"])
                self.assertEqual(found["confirmed"], [])
                self.assertTrue(all(c["review"] is None for c in found["causes"]))

    def test_the_first_screen_reports_what_the_outside_file_holds(self):
        outside_meta = self.client.get("/api/overview").get_json()["meta"]["outside"]
        self.assertEqual(outside_meta["total"], len(self.app.extensions["outside"]))


class Decisions(unittest.TestCase):
    def test_decisions_survive_a_restart_and_belong_to_one_data_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            Reviews(path).set("2026-10-03", "a1", "heat", "rejected", "", "x" * 900)
            kept = Reviews(path).get("2026-10-03", "a1", "heat")
            self.assertEqual((kept["decision"], kept["reviewer"], len(kept["note"])), ("rejected", "Unnamed reviewer", 500))
            self.assertIsNone(Reviews(path).get("2026-10-04", "a1", "heat"))

    def test_an_unreadable_decisions_file_is_treated_as_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text("not json")
            self.assertIsNone(Reviews(path).get("2026-10-03", "a1", "heat"))


if __name__ == "__main__":
    unittest.main()
