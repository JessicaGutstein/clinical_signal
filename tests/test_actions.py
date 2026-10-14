"""Checks for part three: who can act.

Run from the project folder:

    python -m unittest tests.test_actions -v

Four groups. The first checks the mapping file and the lookup rules. The second
checks what Claude is and is not allowed to write. The third runs the real app:
nothing is recommended until a cause is confirmed, and every cause that can be
confirmed today gets an owner from the fixed list. The fourth checks that
people's decisions are kept in order and that the app never sends anything.
"""

from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from clinical_signal import actions, causes, create_app  # noqa: E402

ROW = {"topic": "air_quality", "condition": "any", "outcome": "action", "owner": "Care management", "contact_role": "Care management lead",
       "recommendation": "Contact members with asthma.", "also_consider": [], "why_owner": "Outreach is their work.", "status": "Draft",
       "last_reviewed": "", "source_title": "", "source_url": ""}


def row(**changes):
    return dict(ROW, **changes)


class TheMapping(unittest.TestCase):
    def setUp(self):
        self.mapping = actions.load_mapping()

    def test_every_kind_of_cause_has_an_entry_that_always_applies(self):
        always = {r["topic"] for r in self.mapping if r["condition"] == "any"}
        self.assertEqual(always, set(causes.TOPICS))

    def test_every_entry_names_a_plan_team_and_a_role_and_is_marked_draft(self):
        with open(config.DATA_DIR / "facilities.csv", newline="", encoding="utf-8") as f:
            hospitals = {r["facility_name"] for r in csv.DictReader(f)}
        for r in self.mapping:
            self.assertIn(r["owner"], actions.OWNERS)
            self.assertNotIn(r["owner"], hospitals)
            self.assertTrue(r["contact_role"].endswith(("lead", "analyst")), r["contact_role"])  # a role, never a named person
            self.assertEqual(r["status"], "Draft", "no entry may look approved: no team has seen it")
            self.assertIsNone(actions.PROMISE.search(r["recommendation"]), r["topic"])
            self.assertTrue(r["why_owner"])

    def test_an_entry_that_recommends_no_action_says_so(self):
        for r in self.mapping:
            if r["outcome"] == "monitor":
                self.assertTrue(r["recommendation"].startswith("No action is recommended"), r["topic"])
            if r["outcome"] == "adjust":
                self.assertTrue(r["recommendation"].startswith("Treat this as"), r["topic"])

    def test_a_source_is_a_public_body_and_a_real_link(self):
        for r in self.mapping:
            if r["source_url"]:
                self.assertRegex(r["source_url"], r"^https://([\w.-]+\.)?(cdc\.gov|ahrq\.gov|cms\.gov|airnow\.gov)/")
                self.assertTrue(r["source_title"])

    def test_a_condition_wins_only_when_every_facility_meets_it(self):
        m = [row(topic="x"), row(topic="x", condition="out-of-network", owner="Network and contracting")]
        self.assertEqual(actions.lookup(m, "x", {"Out-of-network"})[0]["owner"], "Network and contracting")
        self.assertEqual(actions.lookup(m, "x", {"In-network"})[0]["owner"], "Care management")
        self.assertEqual(actions.lookup(m, "x", {"Out-of-network", "In-network"})[0]["owner"], "Care management")
        self.assertIsNone(actions.lookup(m, "y", {"In-network"})[0])

    def test_the_real_out_of_network_entries_go_to_contracting(self):
        for topic in ("facility_closure", "labor_action"):
            r, matched = actions.lookup(self.mapping, topic, {"Out-of-network"})
            self.assertEqual((r["owner"], r["outcome"], matched), ("Network and contracting", "action", "out-of-network"))

    def test_a_bad_mapping_file_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = (config.DATA_DIR / actions.MAPPING_FILE).read_text(encoding="utf-8")
            (Path(tmp) / actions.MAPPING_FILE).write_text(good.replace("Care management,", "A named hospital,", 1), encoding="utf-8")
            with self.assertRaises(ValueError):
                actions.load_mapping(Path(tmp))
            self.assertEqual(actions.load_mapping(Path(tmp) / "nowhere"), [])


ALERT = {"title": "COPD and asthma", "subtitle": "Bronx", "period": "last 28 days", "facility_ids": ["F1"],
         "display": {"observed": 120, "expected": 80, "excess": 40}}
FACILITIES = [{"id": "F1", "network": "In-network"}]


def found(decision="confirmed", strength="strong", topic="air_quality"):
    review = {"decision": decision, "reviewer": "A. Analyst", "note": "", "at": "2026-10-05T10:00:00"} if decision else None
    return {"causes": [{"topic": topic, "label": "Poor air quality", "strength": strength, "why": "Poor air may trigger flare-ups.",
                        "review": review, "items": [{"id": "S1", "title": "Air quality alert", "url": "/external/articles/S1.html",
                                                     "source_label": "Weather and air quality"}]}]}


class TheRules(unittest.TestCase):
    def test_nothing_is_recommended_until_a_cause_is_confirmed(self):
        for decision in (None, "rejected", "unsure"):
            out = actions.recommend(ALERT, FACILITIES, found(decision), [row()])
            self.assertEqual(out["recommendations"], [])
            self.assertEqual(out["default"]["owner"], "Clinical analytics")
        nothing = actions.recommend(ALERT, FACILITIES, {"causes": []}, [row()])
        self.assertIn("No outside explanation", nothing["default"]["text"])

    def test_a_confirmed_cause_gets_the_mapped_owner_and_wording(self):
        rec = actions.recommend(ALERT, FACILITIES, found(), [row()])["recommendations"][0]
        self.assertEqual((rec["owner"], rec["text"], rec["outcome_label"]), ("Care management", "Contact members with asthma.", "Recommended action"))
        self.assertIsNone(rec["caution"])

    def test_a_weak_cause_carries_a_caution(self):
        rec = actions.recommend(ALERT, FACILITIES, found(strength="weak"), [row()])["recommendations"][0]
        self.assertIn("rated weak", rec["caution"])

    def test_a_cause_with_no_entry_goes_to_analyst_review(self):
        rec = actions.recommend(ALERT, FACILITIES, found(topic="something_new"), [row()])["recommendations"][0]
        self.assertEqual((rec["outcome"], rec["owner"]), ("unmapped", "Clinical analytics"))

    def test_the_standard_message_carries_the_chain_and_goes_to_a_plan_team(self):
        out = actions.recommend(ALERT, FACILITIES, found(), [row()])
        rec = out["recommendations"][0]
        m = actions.standard_message(out["hotspot"], rec, rec["text"])
        self.assertEqual(m["to"], "Care management lead, Care management")
        for part in ("120 member admissions", "about 80 expected", "Poor air quality", "A. Analyst", "Air quality alert", "Contact members with asthma.", "draft entry"):
            self.assertIn(part, m["body"])


class WhatClaudeMayWrite(unittest.TestCase):
    def setUp(self):
        out = actions.recommend(ALERT, FACILITIES, found(), [row()])
        self.hotspot, self.rec = out["hotspot"], out["recommendations"][0]
        self.given = actions.facts(self.hotspot, self.rec)
        self.good = {"recommendation": "Contact Bronx members with asthma after the air quality alert.",
                     "subject": "COPD and asthma in the Bronx: action requested",
                     "body": "120 member admissions were reported against about 80 expected. The confirmed cause is poor air quality. Please say whether you agree."}

    def test_a_plain_draft_passes(self):
        self.assertIsNone(actions.check_draft(self.good, self.given))

    def test_a_number_it_was_not_given_is_rejected(self):
        self.assertIn("number", actions.check_draft(dict(self.good, body=self.good["body"] + " This could avoid 25 admissions."), self.given))

    def test_a_promise_is_rejected(self):
        self.assertIn("promised", actions.check_draft(dict(self.good, recommendation="Contact members; this will reduce admissions."), self.given))

    def test_another_team_is_rejected(self):
        self.assertIn("team", actions.check_draft(dict(self.good, body=self.good["body"] + " Network and contracting should also act."), self.given))

    def test_a_long_or_empty_draft_is_rejected(self):
        self.assertIsNotNone(actions.check_draft(dict(self.good, recommendation="One. Two. Three."), self.given))
        self.assertIsNotNone(actions.check_draft(dict(self.good, body=""), self.given))

    def test_without_a_key_the_standard_wording_is_used(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(actions.tailor(self.hotspot, self.rec)["written_by"], "standard")

    def test_claude_never_rewords_an_entry_that_recommends_no_action(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}):
            for outcome in ("monitor", "adjust", "unmapped"):
                self.assertEqual(actions.tailor(self.hotspot, dict(self.rec, outcome=outcome))["written_by"], "standard")

    def test_a_rejected_draft_falls_back_and_says_why(self):
        reply = mock.Mock(content=[mock.Mock(type="text", text='{"recommendation": "This will prevent admissions.", "subject": "s", "body": "b"}')])
        client = mock.Mock()
        client.messages.create.return_value = reply
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), mock.patch.dict(sys.modules, {"anthropic": mock.Mock(Anthropic=lambda: client)}):
            out = actions.tailor(self.hotspot, self.rec)
        self.assertEqual(out["written_by"], "standard")
        self.assertIn("rejected", out["note"])

    def test_a_good_draft_is_used_and_claude_was_given_no_facility_list(self):
        import json
        reply = mock.Mock(content=[mock.Mock(type="text", text=json.dumps(self.good))])
        client = mock.Mock()
        client.messages.create.return_value = reply
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "x"}), mock.patch.dict(sys.modules, {"anthropic": mock.Mock(Anthropic=lambda: client)}):
            out = actions.tailor(self.hotspot, self.rec)
        self.assertEqual((out["written_by"], out["text"]), ("claude", self.good["recommendation"]))
        sent = client.messages.create.call_args.kwargs["messages"][0]["content"]
        self.assertIn("standard_recommendation", sent)
        self.assertNotIn("also_consider", sent)


class TodaysHotspots(unittest.TestCase):
    """The real app, with Claude switched off and its own empty decision files."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patch = mock.patch.dict(os.environ, {}, clear=True)
        cls.patch.start()
        cls.app = create_app(reviews_path=Path(cls.tmp.name) / "reviews.json", decisions_path=Path(cls.tmp.name) / "decisions.json")
        cls.client = cls.app.test_client()
        cls.alerts = cls.client.get("/api/overview").get_json()["alerts"]

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.tmp.cleanup()

    def get(self, alert_id):
        return self.client.get(f"/api/alerts/{alert_id}/actions").get_json()

    def post(self, alert_id, topic, step, body):
        return self.client.post(f"/api/alerts/{alert_id}/actions/{topic}/{step}", json=body)

    def test_1_before_anyone_confirms_every_hotspot_needs_analyst_review(self):
        for a in self.alerts:
            out = self.get(a["id"])
            self.assertEqual(out["recommendations"], [], a["id"])
            self.assertEqual(out["default"]["owner"], "Clinical analytics")
        self.assertEqual(self.post(self.alerts[0]["id"], "air_quality", "decision", {"decision": "accepted"}).status_code, 404)

    def test_2_every_cause_that_can_be_confirmed_gets_an_owner_from_the_list(self):
        seen = 0
        for a in self.alerts:
            for c in self.client.get(f"/api/alerts/{a['id']}/causes").get_json()["causes"]:
                self.client.post(f"/api/alerts/{a['id']}/causes/{c['topic']}/review", json={"decision": "confirmed", "reviewer": "Test"})
            out = self.get(a["id"])
            for r in out["recommendations"]:
                seen += 1
                self.assertIn(r["owner"], actions.OWNERS, a["id"])
                self.assertNotEqual(r["outcome"], "unmapped", f"{a['id']} {r['topic']}")
                self.assertEqual((r["stage"], r["written_by"], r["status"]), ("to_decide", "standard", "Draft"))
                self.assertEqual(bool(r["caution"]), r["cause"]["strength"] == "weak")
                self.assertTrue(all(i["url"].startswith("/external/articles/") for i in r["cause"]["items"]))
        self.assertGreater(seen, 15)

    def test_3_accept_hand_off_and_answer_happen_in_order_and_nothing_is_sent(self):
        a, topic = "wave-0-Bronx", "air_quality"
        self.assertEqual(self.post(a, topic, "handoff", {"subject": "s", "body": "b"}).status_code, 400)   # not accepted yet
        r = self.post(a, topic, "decision", {"decision": "accepted", "reviewer": "J. Analyst"}).get_json()["recommendations"]
        rec = next(x for x in r if x["topic"] == topic)
        self.assertEqual((rec["stage"], rec["draft_by"], rec["decision"]["edited"]), ("accepted", "standard", False))
        self.assertEqual(rec["draft"]["to"], "Care management lead, Care management")
        self.assertEqual(self.post(a, topic, "answer", {"answer": "agreed"}).status_code, 400)             # not handed off yet
        self.assertEqual(self.post(a, topic, "handoff", {"subject": "s", "body": " "}).status_code, 400)   # an empty message
        sent = self.post(a, topic, "handoff", {"subject": "Edited subject", "body": "Edited body", "to": "Some Hospital"}).get_json()
        rec = next(x for x in sent["recommendations"] if x["topic"] == topic)
        self.assertEqual(rec["stage"], "handed_off")
        self.assertEqual(rec["decision"]["handoff"]["to"], "Care management lead, Care management")       # who it goes to cannot be changed
        self.assertEqual(rec["decision"]["handoff"]["body"], "Edited body")
        rec = next(x for x in self.post(a, topic, "answer", {"answer": "declined", "note": "Already doing this"}).get_json()["recommendations"] if x["topic"] == topic)
        self.assertEqual(rec["stage"], "owner_declined")
        self.assertEqual(self.post(a, topic, "answer", {"answer": "maybe"}).status_code, 400)
        rec = next(x for x in self.post(a, topic, "decision", {"decision": None}).get_json()["recommendations"] if x["topic"] == topic)
        self.assertEqual((rec["stage"], rec["decision"]), ("to_decide", None))
        # The app has no way to send a message: nothing in part three opens a connection.
        source = (Path(actions.__file__)).read_text(encoding="utf-8")
        for word in ("smtplib", "requests.", "urllib", "sendmail", "webhook"):
            self.assertNotIn(word, source)

    def test_4_an_edited_recommendation_is_what_the_message_carries(self):
        a, topic = "pair-F011-19", "infection_control"
        r = self.post(a, topic, "decision", {"decision": "accepted", "text": "Ask the three homes for their correction plans."}).get_json()
        rec = next(x for x in r["recommendations"] if x["topic"] == topic)
        self.assertTrue(rec["decision"]["edited"])
        self.assertIn("Ask the three homes for their correction plans.", rec["draft"]["body"])
        self.assertEqual(rec["owner"], "Network and contracting")
        self.post(a, topic, "decision", {"decision": None})

    def test_5_taking_back_the_confirmation_takes_back_the_recommendation(self):
        a = "pair-F055-0"
        self.assertTrue(self.get(a)["recommendations"])
        self.client.post(f"/api/alerts/{a}/causes/childhood_virus/review", json={"decision": "rejected"})
        out = self.get(a)
        self.assertEqual(out["recommendations"], [])
        self.assertIsNotNone(out["default"])

    def test_6_detection_is_unchanged_by_part_three(self):
        before = [(a["id"], a["reported"], a["rank"]) for a in self.alerts]
        after = [(a["id"], a["reported"], a["rank"]) for a in self.client.get("/api/overview").get_json()["alerts"]]
        self.assertEqual(before, after)


class TheLoop(unittest.TestCase):
    def test_an_earlier_hand_off_is_found_on_a_later_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = actions.Decisions(Path(tmp) / "d.json")
            store.decide("2026-10-01", "h1", "air_quality", "accepted", "Do it", False, "A", "")
            store.hand_off("2026-10-01", "h1", "air_quality", {"to": "Care management lead, Care management", "subject": "s", "body": "b"})
            self.assertIsNone(store.earlier("2026-10-01", "h1", "air_quality"))
            later = store.earlier("2026-10-03", "h1", "air_quality")
            self.assertEqual((later["as_of"], later["days"]), ("2026-10-01", 2))
            self.assertIsNone(store.earlier("2026-10-03", "h2", "air_quality"))
            self.assertEqual(actions.Decisions(Path(tmp) / "d.json").get("2026-10-01", "h1", "air_quality")["decision"], "accepted")  # survives a restart


if __name__ == "__main__":
    unittest.main()
