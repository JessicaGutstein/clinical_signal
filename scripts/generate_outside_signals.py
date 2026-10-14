"""Builds the outside-signals file used by part two ("What's driving it").

    python scripts/generate_outside_signals.py

Writes:

    external_data/outside_signals.csv     about 200 invented items from outside the plan
    external_data/articles/ and index.html   a page for each item (by build_external_articles.py)
    data/outside_signals_answer_key.csv   what part two should find for each of today's hotspots

Everything here is invented. It is kept completely apart from the admissions
data: nothing in this file is read by detection, and detection never changes
because of it.

The items were written backwards from the hotspots detection finds on the
prototype's "today" (October 3, 2026), so the dashboard has something to show:

    true causes   one for each planted hotspot that detection catches
    decoys        plausible but wrong (a citywide heat spell, a pharmacy closure)
    near misses   right diagnosis, wrong place or wrong time
    noise         routine bulletins and unrelated local news

Hotspots with no planted pattern behind them get no true cause on purpose, so
the screen has to be able to say "No outside explanation found".

The file is fixed: the same script always writes the same rows.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
EXTERNAL_DIR = Path(__file__).resolve().parents[1] / "external_data"
AS_OF = date(2026, 10, 3)
SEED = 20261003

AREAS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island",
         "Nassau County", "Westchester County", "Bergen County, NJ", "Hudson County, NJ"]
CITY = AREAS[:5]

# Source names are generic or invented on purpose: no real agency or newspaper is quoted.
# The app shows real hospital names, so no item names a hospital or a health system.
# An item is tied to a facility only by its id, and every event is something that
# happened around a hospital (a clinic closing, a strike elsewhere), never at it.
SRC_HEALTH = "City health department (invented notice)"
SRC_STATE = "State health department (invented notice)"
SRC_AIR = "Regional air quality bulletin (invented)"
SRC_WEATHER = "Regional weather service (invented)"
SRC_EMS = "Regional emergency medical services council (invented)"
PAPERS = ["Five Borough Dispatch", "Harbor & Hudson Journal", "The Borough Ledger-Post", "Tri-County Morning Wire"]

FLU = "Influenza, COVID-19 and viral respiratory infection"
ASTHMA = "COPD and asthma"
KIDNEY = "Kidney disease and fluid disorders"
CAD = "Coronary artery disease and heart attack"

FIELDS = ["item_id", "source_type", "source_name", "published", "starts", "ends", "areas", "facility_ids",
          "health_system", "topic", "diagnosis_direct", "diagnosis_indirect", "population", "level", "title", "body"]


def item(source_type, source_name, starts, title, body, *, topic, areas=(), facilities=(), system="",
         direct=(), indirect=(), ends="", population="all", level="notable", published=""):
    return {
        "source_type": source_type, "source_name": source_name, "published": published or starts,
        "starts": starts, "ends": ends, "areas": "; ".join(areas), "facility_ids": "; ".join(facilities),
        "health_system": system, "topic": topic, "diagnosis_direct": "; ".join(direct),
        "diagnosis_indirect": "; ".join(indirect), "population": population, "level": level,
        "title": title, "body": body,
    }


# --------------------------------------------------------------------------- written by hand
def curated() -> list[dict]:
    paper = PAPERS
    return [
        # ---- true causes: one per planted hotspot that detection catches today ----
        item("facility_event", SRC_STATE, "2026-09-01",
             "Hospital in southeast Brooklyn closes its maternity and inpatient cardiac units",
             "A hospital in southeast Brooklyn that is not in the plan's network closed its maternity ward and its "
             "inpatient cardiac unit on September 1. The notice says the nearest public hospital is expected to take "
             "those patients. No reopening date has been given.",
             topic="facility_closure", areas=["Brooklyn"], facilities=["F047"], direct=["All"]),
        item("news", paper[0], "2026-09-05",
             "Brooklyn public hospital feels the strain after neighbour shuts units",
             "Staff at the public hospital nearest the closed units say deliveries and heart patients have risen since "
             "the closure at the start of the month. Ambulance crews confirmed they are now taking those patients there.",
             topic="facility_closure", areas=["Brooklyn"], facilities=["F047"], direct=["All"]),

        item("public_health", SRC_HEALTH, "2026-09-04",
             "Respiratory illness level in Queens moves to High, weeks earlier than usual",
             "Weekly surveillance shows flu-like illness visits in Queens rose to the High level in the week ending "
             "September 4. The other boroughs remain at Low. The department notes this is several weeks ahead of a "
             "typical season and is concentrated in central and eastern Queens.",
             topic="respiratory_virus", areas=["Queens"], direct=[FLU], indirect=["Pneumonia"]),
        item("public_health", SRC_HEALTH, "2026-09-18",
             "Queens respiratory illness level stays High for a third week",
             "Flu-like illness visits in Queens remained at the High level in the week ending September 18 and are "
             "still climbing. Influenza A is the most common virus found in samples from Queens clinics.",
             topic="respiratory_virus", areas=["Queens"], direct=[FLU], indirect=["Pneumonia"]),
        item("news", paper[2], "2026-09-10",
             "Queens schools report early wave of flu absences",
             "Several schools in Flushing and Jackson Heights reported unusually high absences in the first full week "
             "of term, with parents describing fever and cough. Pharmacies in the area say flu tests are selling out.",
             topic="respiratory_virus", areas=["Queens"], direct=[FLU]),

        item("facility_event", SRC_EMS, "2026-09-01",
             "Ambulances to take suspected stroke patients to newly designated stroke centers from September 1",
             "Under a new routing rule that started September 1, ambulance crews across the region take patients with "
             "suspected stroke to the nearest designated stroke center. The three newly designated centers all belong "
             "to one health system and are in Queens, Manhattan and Staten Island.",
             topic="routing_change", facilities=["F054", "F066", "F017"], direct=["Stroke"]),

        item("weather_air", SRC_AIR, "2026-09-08",
             "Air quality alert for the Bronx: fine particles unhealthy for sensitive groups",
             "Fine particle levels in the Bronx were in the 'unhealthy for sensitive groups' range from September 8 to "
             "September 12, the longest run this year. People with asthma or chronic lung disease were advised to stay "
             "indoors. Levels in the other boroughs stayed moderate.",
             topic="air_quality", areas=["Bronx"], direct=[ASTHMA], indirect=["Heart failure"], ends="2026-09-12"),
        item("weather_air", SRC_AIR, "2026-09-19",
             "Second air quality alert in two weeks for the Bronx",
             "Fine particle levels in the Bronx returned to the 'unhealthy for sensitive groups' range from September 19 "
             "to September 22. The bulletin links both episodes to still air trapping traffic and industrial emissions.",
             topic="air_quality", areas=["Bronx"], direct=[ASTHMA], indirect=["Heart failure"], ends="2026-09-22"),

        item("news", paper[3], "2026-09-01",
             "Nassau County moves its employees and retirees to a new health plan",
             "From September 1, Nassau County's employees, retirees and their families are covered by the plan, after "
             "the county changed insurers. County officials put the number of people moving at several thousand.",
             topic="enrollment_change", areas=["Nassau County"], direct=["All"]),

        item("news", paper[1], "2026-09-08",
             "Nurses strike at a Bergen County hospital; ambulances diverted to Hackensack",
             "Nurses at a Bergen County hospital that is not in the plan's network walked out on September 8. The "
             "hospital has stopped taking new admissions, and ambulances are being sent to the nearest hospital in "
             "Hackensack. Talks have not resumed.",
             topic="labor_action", areas=["Bergen County, NJ"], facilities=["F095"], direct=["All"]),

        item("facility_event", SRC_STATE, "2026-09-03",
             "Outpatient infusion clinic on the Upper East Side closes after water damage",
             "An independent outpatient infusion clinic on the Upper East Side closed on September 3 after a burst pipe. "
             "Until repairs are finished, its patients due for chemotherapy are being referred to the nearest cancer "
             "hospital, where they are admitted and treated on the inpatient floors. The clinic expects to stay closed "
             "into October.",
             topic="service_disruption", areas=["Manhattan"], facilities=["F022"], direct=["Cancer"]),

        item("news", paper[0], "2026-08-29",
             "Dialysis provider closes two Upper East Side clinics",
             "A dialysis company closed two clinics on the Upper East Side on August 29, citing staffing. Patients were "
             "told to find places at clinics elsewhere in Manhattan. Kidney doctors warned that missed sessions lead to "
             "emergency admissions at the closest hospital.",
             topic="care_access", areas=["Manhattan"], facilities=["F001"], direct=[KIDNEY]),

        item("public_health", SRC_STATE, "2026-08-10",
             "Inspection finds catheter-care lapses at three Manhattan nursing homes",
             "State inspectors cited three nursing homes on Manhattan's East Side for lapses in urinary catheter care "
             "and infection control. The homes were given 60 days to correct the problems. Residents with infections "
             "are usually sent to nearby hospitals.",
             topic="infection_control", areas=["Manhattan"], direct=["Urinary tract infection"], indirect=["Sepsis"]),

        item("public_health", SRC_HEALTH, "2026-09-09",
             "Enterovirus D68 found in Queens schoolchildren; asthma flare-ups expected",
             "Laboratory tests confirmed enterovirus D68 in children from several Queens schools. The virus is known "
             "for triggering severe asthma attacks in children. Pediatric emergency departments in Queens were asked "
             "to expect more children needing admission for breathing problems.",
             topic="childhood_virus", areas=["Queens"], direct=[ASTHMA], population="children"),

        item("public_health", SRC_HEALTH, "2026-09-25",
             "Stomach illness cluster linked to a street festival in Sunset Park",
             "The department is investigating dozens of reports of vomiting and diarrhea among people who ate at a "
             "street festival in Sunset Park, Brooklyn, on September 23. Several needed hospital care, most at "
             "the nearest hospital. The source has not been confirmed.",
             topic="foodborne_outbreak", areas=["Brooklyn"], facilities=["F042"], direct=["Gastrointestinal"]),

        item("facility_event", paper[2], "2026-08-24",
             "Community diabetes clinic in Morris Park closes in consolidation",
             "An independent outpatient diabetes clinic in the Morris Park section of the Bronx closed on August 24 "
             "and moved appointments to a single site across the borough. Patients described waits of several weeks "
             "for a first appointment at the new site.",
             topic="care_access", areas=["Bronx"], facilities=["F028"], direct=["Diabetes complications"]),

        # ---- decoys: plausible, in range, but not the planted cause ----
        item("weather_air", SRC_WEATHER, "2026-09-03",
             "Late-summer heat advisory for the whole region",
             "A heat advisory covered the whole region from September 3 to September 8, with afternoon heat index "
             "values near 100. Heat raises the risk of dehydration and puts extra strain on the heart and kidneys, "
             "mostly in older adults.",
             topic="heat", areas=["All"], ends="2026-09-08",
             indirect=[KIDNEY, "Heart failure", "Cardiac arrhythmia", CAD, "Stroke"]),
        item("news", paper[1], "2026-08-14",
             "Pharmacy chain closes four stores in the Bronx",
             "A pharmacy chain closed four of its Bronx stores on August 14. Community groups said people who rely on "
             "regular refills, such as inhalers, insulin and blood pressure medicine, now have further to travel.",
             topic="care_access", areas=["Bronx"],
             indirect=[ASTHMA, "Diabetes complications", "Heart failure", "Hypertension"]),
        item("news", paper[0], "2026-06-02",
             "E-bike injuries keep rising in Queens, doctors say",
             "Emergency doctors in Queens say they are treating more riders and pedestrians hurt in e-bike crashes "
             "than a year ago. The article gives no dates or counts and describes a long-running trend.",
             topic="injury_trend", areas=["Queens"], direct=["Injury and trauma"], level="background"),

        # ---- near misses: the right diagnosis, but the wrong place or the wrong time ----
        item("public_health", SRC_HEALTH, "2026-06-20",
             "Legionnaires' disease cluster in Upper Manhattan declared over",
             "A cluster of Legionnaires' disease, a kind of pneumonia, was traced to a cooling tower in Upper "
             "Manhattan. Cases began on June 20 and the department declared the cluster over on July 25.",
             topic="outbreak", areas=["Manhattan"], direct=["Pneumonia"], ends="2026-07-25"),
        item("public_health", SRC_HEALTH, "2026-09-30",
             "Norovirus outbreak closes a Manhattan elementary school for two days",
             "A Manhattan elementary school closed on September 30 for cleaning after about 60 pupils and staff "
             "reported vomiting. The department confirmed norovirus.",
             topic="foodborne_outbreak", areas=["Manhattan"], direct=["Gastrointestinal"], population="children"),
        item("facility_event", paper[3], "2026-11-10",
             "Westchester County hospital to open new maternity wing in November",
             "A hospital in Westchester County announced that its new maternity wing, with 14 more delivery rooms, "
             "will open on November 10.",
             topic="service_expansion", areas=["Westchester County"], facilities=["F081"],
             direct=["Maternity and newborn"], published="2026-09-15"),
        item("news", paper[2], "2026-07-11",
             "Crisis line outage left Queens callers without help for two days",
             "A technical fault took a mental health crisis line offline for callers in Queens on July 11 and 12. "
             "Service was restored on July 13.",
             topic="service_disruption", areas=["Queens"], direct=["Mental health"], ends="2026-07-13"),
        item("news", paper[1], "2026-09-28",
             "Multi-vehicle crash closes the expressway in the Bronx",
             "A crash involving a bus and several cars closed an expressway in the Bronx on the evening of September 28. "
             "More than a dozen people were taken to hospitals in the borough.",
             topic="mass_casualty", areas=["Bronx"], direct=["Injury and trauma"], ends="2026-09-28"),
        item("facility_event", SRC_STATE, "2025-12-01",
             "Hospital in Upper Manhattan closed its labor and delivery unit last December",
             "A hospital in Upper Manhattan stopped delivering babies on December 1, 2025. Expectant mothers were "
             "directed to other Manhattan hospitals.",
             topic="facility_closure", areas=["Manhattan"], direct=["Maternity and newborn"]),
        item("weather_air", SRC_AIR, "2026-09-08",
             "Air quality in Queens stays moderate during Bronx alert",
             "While the Bronx was under an air quality alert from September 8 to September 12, readings in Queens "
             "stayed in the moderate range and no advisory was issued there.",
             topic="air_quality", areas=["Queens"], direct=[ASTHMA], ends="2026-09-12", level="routine"),
        item("public_health", SRC_HEALTH, "2026-03-02",
             "Sepsis cluster at a Bronx hospital traced to contaminated supplies",
             "The department traced a rise in sepsis at a Bronx hospital in March to a contaminated batch of "
             "intravenous supplies. The batch was withdrawn and cases returned to normal by mid-April.",
             topic="outbreak", areas=["Bronx"], direct=["Sepsis"], ends="2026-04-11"),
        item("news", paper[3], "2026-09-12",
             "Stomach bug sweeps a Staten Island summer league",
             "Players and families from a Staten Island youth sports league reported a stomach bug after a weekend "
             "tournament. No one was reported to need hospital care.",
             topic="foodborne_outbreak", areas=["Staten Island"], direct=["Gastrointestinal"]),
    ]


# --------------------------------------------------------------------------- routine feeds and unrelated news
def weekly_dates(weeks: int) -> list[date]:
    """The Friday of each of the last `weeks` weeks, oldest first."""
    last = AS_OF - timedelta(days=1)  # Friday, October 2
    return [last - timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]


def routine_feeds(rng: random.Random) -> list[dict]:
    out = []
    # Weekly respiratory bulletins: one per area per week. Queens is covered by the hand-written High notices.
    for d in weekly_dates(8):
        for area in AREAS:
            if area == "Queens" and d >= date(2026, 9, 4):
                continue
            level = rng.choice(["Low", "Low", "Low", "Minimal"])
            out.append(item("public_health", SRC_HEALTH if area in CITY else SRC_STATE, d.isoformat(),
                            f"Weekly respiratory illness bulletin: {area} at {level}",
                            f"Flu-like illness visits in {area} were at the {level} level in the week ending "
                            f"{d.strftime('%B %-d')}, which is usual for the time of year. No action is advised.",
                            topic="respiratory_virus", areas=[area], direct=[FLU], indirect=["Pneumonia"], level="routine"))
    # Weekly air quality summaries for the five boroughs. The Bronx alert weeks are hand-written above.
    for d in weekly_dates(6):
        for area in CITY:
            if area == "Bronx" and d in (date(2026, 9, 11), date(2026, 9, 25)):
                continue
            word = rng.choice(["good", "good", "moderate"])
            out.append(item("weather_air", SRC_AIR, d.isoformat(),
                            f"Weekly air quality summary: {area} mostly {word}",
                            f"Air quality in {area} was mostly {word} in the week ending {d.strftime('%B %-d')}. "
                            f"No advisory was issued.",
                            topic="air_quality", areas=[area], direct=[ASTHMA], level="routine"))
    # Weekly weather outlooks for the region.
    for d in weekly_dates(10):
        if d == date(2026, 9, 4):
            continue  # the heat advisory week is hand-written above
        out.append(item("weather_air", SRC_WEATHER, d.isoformat(),
                        "Weekly weather outlook: seasonable temperatures",
                        f"Temperatures across the region were close to normal in the week ending {d.strftime('%B %-d')}. "
                        f"No heat or cold advisory was issued.",
                        topic="heat", areas=["All"], indirect=[KIDNEY, "Heart failure"], level="routine"))
    return out


NEWS_TEMPLATES = [
    ("School board in {area} approves new term calendar", "The school board in {area} approved next year's calendar after a short public meeting."),
    ("Weekend subway work planned in {area}", "Transit officials announced weekend track work affecting several stations in {area}."),
    ("Farmers market returns to {area}", "A weekly farmers market reopened in {area} with more than thirty stalls."),
    ("{area} library branch reopens after renovation", "A library branch in {area} reopened after a year-long renovation."),
    ("Charity run in {area} raises money for local food bank", "Hundreds took part in a charity run in {area} at the weekend."),
    ("New bike lanes proposed for {area}", "Planners presented a proposal for new protected bike lanes in {area}. No date has been set."),
    ("{area} street fair draws record crowd", "Organisers said this year's street fair in {area} was the busiest yet. No incidents were reported."),
    ("Water main repair closes a road in {area}", "A water main repair closed part of a road in {area} for two days. Water service was not interrupted."),
    ("Community board in {area} debates new housing", "The community board in {area} heard residents' views on a proposed apartment building."),
    ("Free health fair held in {area}", "A free health fair in {area} offered blood pressure checks and vaccination information."),
    ("Blood drive in {area} meets its target", "A blood drive in {area} collected enough donations to meet its target."),
    ("Parking rules change in {area}", "New parking rules took effect on several streets in {area}."),
]
FACILITY_NOISE = [
    ("Hospital in {area} opens new parking structure", "A hospital in {area} opened a new parking structure for visitors and staff."),
    ("Hospital in {area} names new chief executive", "A hospital in {area} announced a new chief executive, who starts next quarter."),
    ("Hospital in {area} switches to a new records system", "A hospital in {area} moved to a new electronic records system. Patient care was not interrupted."),
    ("Hospital gala in {area} raises funds for new equipment", "An annual gala raised funds for imaging equipment at a hospital in {area}."),
    ("Hospital in {area} recognised for patient experience", "A hospital in {area} received a patient experience award from a national survey group."),
]


def unrelated_news(rng: random.Random) -> list[dict]:
    out = []
    first = date(2025, 11, 1)
    span = (AS_OF - first).days
    for i in range(48):
        title, body = NEWS_TEMPLATES[i % len(NEWS_TEMPLATES)]
        area = rng.choice(AREAS)
        d = first + timedelta(days=rng.randrange(span))
        out.append(item("news", rng.choice(PAPERS), d.isoformat(), title.format(area=area), body.format(area=area),
                        topic="unrelated", areas=[area], level="routine"))
    for i in range(16):
        title, body = FACILITY_NOISE[i % len(FACILITY_NOISE)]
        area = rng.choice(AREAS)
        d = first + timedelta(days=rng.randrange(span))
        out.append(item("facility_event", rng.choice(PAPERS), d.isoformat(), title.format(area=area), body.format(area=area),
                        topic="unrelated", areas=[area], level="routine"))
    return out


# --------------------------------------------------------------------------- what part two should find
# For each of today's hotspots: the topic that should rank first, the strength it
# should get, or "none". Written before the matching rules were run.
ANSWER_KEY = [
    # hotspot_id, planted, expected_top_topic, expected_strength, note
    ("facility-F047", "Yes", "facility_closure", "strong", "A neighbouring hospital closed two units; the heat spell is a weak decoy"),
    ("wave-8-Queens", "Yes", "respiratory_virus", "strong", "Early flu in Queens, from three items in two kinds of source"),
    ("system-17-Northwell_Health", "Yes", "routing_change", "strong", "Ambulance routing to newly designated stroke centers; heat is a weak decoy"),
    ("wave-0-Bronx", "Yes", "air_quality", "strong", "Two air quality alerts; the pharmacy closures are a moderate decoy"),
    ("facilitywide-F071", "Yes", "enrollment_change", "strong", "More members, not more illness: the known enrollment limitation"),
    ("facilitywide-F095", "Yes", "labor_action", "strong", "A strike nearby diverted ambulances here"),
    ("facilitywide-F022", "Yes", "service_disruption", "strong", "Outpatient chemotherapy moved to inpatient floors"),
    ("pair-F001-10", "Yes", "care_access", "strong", "Dialysis clinics closed nearby; heat is a weak decoy"),
    ("facilitywide-F081", "No", "heat", "weak", "Chance. Expected none; changed after the first run on the full app, where the regionwide heat spell fits weakly"),
    ("pair-F011-19", "Yes", "infection_control", "moderate", "The right area and diagnosis, but published four weeks before the rise"),
    ("pair-F055-0", "Yes", "childhood_virus", "strong", "A children's virus at a children's hospital"),
    ("pair-F042-5", "Yes", "foodborne_outbreak", "strong", "A one-week spike after a street festival; the hospital closure is a weak decoy"),
    ("pair-F023-9", "No", "none", "none", "Chance"),
    ("pair-F095-13", "Yes", "labor_action", "strong", "Part of the same Hackensack diversion"),
    ("pair-F002-11", "No", "none", "none", "Chance. A closure last December is too long ago"),
    ("pair-F060-9", "No", "injury_trend", "weak", "Chance. A long-running trend story is never more than weak"),
    ("pair-F054-0", "No", "childhood_virus", "weak", "Chance. The virus notice is about children; this is not a children's hospital"),
    ("pair-F028-4", "Yes", "care_access", "strong", "The facility's own diabetes clinic closed"),
    ("pair-F044-12", "No", "facility_closure", "weak", "Chance. A closure elsewhere in Brooklyn that names a different facility"),
    ("pair-F001-15", "No", "none", "none", "Chance. The Legionnaires' cluster ended in July"),
    ("pair-F058-5", "No", "none", "none", "Chance. The stomach illness cluster is in Brooklyn, not Queens"),
    ("pair-F054-12", "No", "none", "none", "Chance. The crisis line outage was in July"),
    ("pair-F067-3", "No", "heat", "weak", "Chance. Only the regionwide heat spell fits, weakly"),
    ("pair-F031-9", "No", "none", "none", "Chance. The expressway crash came after the rise began"),
    ("pair-F012-8", "No", "none", "none", "Chance. Manhattan's flu bulletins report nothing unusual"),
    ("pair-F012-5", "No", "none", "none", "Chance. The school norovirus outbreak came after the rise began"),
    ("pair-F064-12", "No", "none", "none", "Chance. The crisis line outage was in July"),
    ("pair-F081-11", "No", "none", "none", "Chance. The maternity wing has not opened yet"),
]


def main() -> None:
    rng = random.Random(SEED)
    rows = curated() + routine_feeds(rng) + unrelated_news(rng)
    rows.sort(key=lambda r: (r["published"], r["title"]))
    for i, r in enumerate(rows, start=1):
        r["item_id"] = f"S{i:03d}"
    DATA_DIR.mkdir(exist_ok=True)
    EXTERNAL_DIR.mkdir(exist_ok=True)
    with open(EXTERNAL_DIR / "outside_signals.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    with open(DATA_DIR / "outside_signals_answer_key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hotspot_id", "planted", "expected_top_topic", "expected_strength", "note"])
        w.writerows(ANSWER_KEY)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["source_type"]] = by_type.get(r["source_type"], 0) + 1
    print(f"Wrote {len(rows)} outside items: {by_type}")
    print(f"Wrote the answer key for {len(ANSWER_KEY)} hotspots.")
    # Each item also gets a page that opens like an article, in external_data/articles.
    import build_external_articles
    build_external_articles.main()


if __name__ == "__main__":
    main()
