# Humana Clinical Signal: hotspot detection prototype

Finds where a health plan's member admissions are unusually high and shows them
on a bubble map of the New York region. Part one, detecting the hotspot, and part two, what may be
driving it, are built. Part three, who can act, comes later.

This is a prototype built on synthetic data. It is not an official Humana product.

- The full write-up is in **Clinical Signal - Hotspot Detection Guide.docx**.
- What was tested, and how it came out, is in **Clinical Signal - Evaluation Log.docx**.
- Every design question and answer is in **Clinical Signal - Decision Log.docx**.
- Where the data would come from is in **Clinical Signal - Where the Data Comes From.docx**.

## Start it

On a Mac, double-click `start.command`. The first run takes about a minute to
set up. Your browser opens at http://127.0.0.1:5050.

Or from Terminal:

```bash
cd ~/Desktop/"Clinical Analytics"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Press Ctrl+C in the Terminal window to stop it.

## What is in this folder

```
run.py                  starts the app
start.command           double-click launcher for Mac
config.py               every detection threshold, in one place
requirements.txt        Python packages needed

clinical_signal/        the application
  data_loader.py        reads the admissions file into daily counts
  detection/
    comparisons.py      the four comparisons and the statistical gate
    rollup.py           groups related alerts into one
    ranking.py          priority score and the top 10 cut
    engine.py           runs the steps above in order
  summary.py            writes the short summary of a hotspot (AI, part one)
  causes.py             part two: shortlists outside items by fixed rules; AI explains them
  reviews.py            part two: a person confirms or rejects each possible cause
  actions.py            part three: the owner and recommendation for each confirmed cause; AI rewords and drafts the hand-off
  routes.py             the page and the data it requests
  templates/            the page
  static/               styles, scripts, map outlines, fonts

data/
  synthetic_admissions.csv           173,014 synthetic member admissions
  facilities.csv                     the 100 facilities: type, health system, network status, coordinates
  membership_by_area.csv             members living in each borough or county, now and a year ago
  icd10_codes.csv                    the ICD-10 codes used, with plain names and meanings
  planted_hotspots_answer_key.csv    the evaluation set: 30 cases and what should happen
  action_mapping.csv                 part three: each kind of cause mapped to an owner and a standard recommendation
  action_decisions.json              part three: what people decided on each recommendation (created on first use)
  outside_signals_answer_key.csv     part two: what should be found for each of today's hotspots
  cause_reviews.json                 part two: decisions people have made (created on first use)

scripts/
  generate_data.py      rebuilds the synthetic admissions file and the evaluation set
  run_evaluation.py     scores detection against the evaluation set
  generate_outside_signals.py   rebuilds the outside items and their answer key
  build_external_articles.py    writes a page for each outside item into external_data/articles

external_data/
  outside_signals.csv   part two: 196 invented outside items (notices, weather, news, events)
  articles/             one page per item; an item on the screen is a link to its page
  index.html            a list of every item

tests/
  test_detection.py     checks the rules, the counts, and the evaluation set
  dashboard_checks.py   drives a browser to check the screen against detection
  test_causes.py        part two: the matching rules, the answer key, the AI checks, and decisions
  test_actions.py       part three: the mapping, the lookup rules, the AI checks, and the order of decisions
```

## Check that it works

```bash
python -m unittest discover tests -v      # the rules and the counts
python scripts/run_evaluation.py          # the 30 evaluation cases, one line each
```

`tests/dashboard_checks.py` compares what the screen shows with what detection
found. It needs the `playwright` package and the app running, so it is run during
testing and its results are kept in the evaluation log.

## Change the rules

Edit `config.py` and restart. The gate (2 standard deviations, 6 extra admissions
for one diagnosis at one facility), the rollup minimums, and the size of the top
list are all there. So are the two counting switches: counts are admissions
actually reported, with no scaling up for late reports.

## What's driving it (part two)

The second tab of the Summary panel looks outside the plan's own data for what may be
behind a hotspot. The outside items are in `external_data/outside_signals.csv`, each with its own page in `external_data/articles`. They are invented,
kept apart from the admissions data, and never used by detection.

1. Fixed rules keep the items that fit the hotspot on place, timing, and diagnosis, and
   rate each possible cause strong, moderate, or weak.
2. With an API key set, Claude reads the shortlisted items and writes how each could lead
   to the admissions. It can lower a rating, never raise one, and never states a cause as fact.
3. A person confirms or rejects each possible cause. Decisions are saved in
   `data/cause_reviews.json`. Delete that file to start again.

When nothing fits, the tab says "No outside explanation found".

## AI summaries

Detection uses no AI. The short summary of each hotspot uses fixed wording unless
an Anthropic API key is set before starting:

```bash
export ANTHROPIC_API_KEY="your key"
python run.py
```

The facilities are real hospitals in the New York area, with their real names,
locations, and health systems. Everything else is synthetic: the member
admissions, the hotspots, the costs, the network status, and the member counts.
Nothing here describes what really happened at any hospital.

## Who can act (part three)

The third tab names who can do something about a hotspot and what they would normally do.
It only makes a recommendation for a cause a person has confirmed on the second tab. With
none confirmed it says "Needs analyst review".

The owner and the recommendation come from one file, `data/action_mapping.csv`. Each row maps
a kind of cause to a business area, a point of contact (a role, not a person), and that
area's standard recommendation. A row can carry a condition, for example `out-of-network`,
which wins when every facility in the hotspot meets it. To change a recommendation or an
owner, edit the file and restart.

In a real plan each business area would write and approve its own rows. Here every row is a
draft written for the prototype and is shown as "Draft". Eight rows link to one of seven public sources
(CDC, EPA, AHRQ, CMS) as background; the source shows that kind of action is established
practice, not that it would work on a given hotspot.

1. Fixed rules look the confirmed cause up in the mapping.
2. With an API key set, Claude rewords a recommended action for the hotspot and drafts the
   hand-off message. A draft with a number it was not given, a promise that the action will
   work, or a different team is rejected and the standard wording is used. Claude never
   rewords a row that recommends no action.
3. An analyst accepts, edits, or declines. On accept the hand-off message is shown to copy
   and send. The app sends nothing.
4. The owner's answer (agreed, or not the right action) is recorded.

Decisions are kept in `data/action_decisions.json`.

