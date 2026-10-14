"""Settings for hotspot detection.

Every number that decides what counts as a hotspot lives here, so the rules can
be tuned without touching the detection code.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
# Everything from outside the plan (part two): the outside items and a page for each one.
# Kept apart from the admissions data. Detection never reads this folder.
EXTERNAL_DIR = BASE_DIR / "external_data"

# The "today" of the prototype. None means the latest admission date in the data.
# Set to an ISO date such as "2026-04-04" to replay detection for an earlier day.
AS_OF = None

# Web server
HOST = "127.0.0.1"
PORT = 5050  # 5000 is taken by AirPlay Receiver on recent versions of macOS

# --- Counting -------------------------------------------------------------
# Totals on screen are admissions actually reported: recent days are NOT scaled
# up for reports still to come, so a hospital's count can be checked by hand.
# The price is that a hotspot that is just starting can show a few days later.
ADJUST_FOR_REPORTING_LAG = False
# An admission without a claim only has a preliminary diagnosis, which is wrong
# about one time in eight. Each is still counted once, but shared across the
# diagnosis groups that preliminary diagnosis has turned into in the past.
# Without this, recent weeks pile up in the wrong groups and look like hotspots.
REWEIGHT_PRELIMINARY = True

# --- Window ---------------------------------------------------------------
WINDOW_DAYS = 28  # rolling detection window
WEEK_DAYS = 7

# --- Gate: what qualifies as a hotspot --------------------------------------
# A comparison fires when the count is at least Z_GATE standard deviations above
# its baseline AND the excess is at least the minimum volume for that level.
Z_GATE = 2.0
MIN_EXCESS = {
    "pair": 6,        # one facility x one diagnosis group
    "facility": 10,   # one facility, all diagnosis groups
    "diagnosis": 10,  # one diagnosis group, all facilities
    "group": 10,      # a rolled-up set of slices
}

# --- Rollups ----------------------------------------------------------------
# Same diagnosis flagged at this many facilities in one area becomes one alert.
ROLLUP_MIN_FACILITIES = 3
# The same number applies to one health system: the same diagnosis at this many of
# a system's facilities, wherever they are, becomes one system-wide hotspot.
# Facilities with no system ("Independent") are never grouped this way.
INDEPENDENT = "Independent"
# ...or this share of the area's facilities that regularly admit the diagnosis,
# whichever is greater.
ROLLUP_MIN_SHARE = 0.15
# A facility counts as regularly admitting a diagnosis at this many a year.
REGULAR_ADMITS_PER_YEAR = 12
# One facility flagged for this many diagnosis groups becomes one alert.
ROLLUP_MIN_DIAGNOSES = 3
# A facility-wide or plan-wide alert is dropped when more specific alerts
# already account for at least this share of its excess.
PARENT_EXPLAINED_SHARE = 0.5

# --- Ranking ----------------------------------------------------------------
TOP_N = 10  # high-priority alerts shown in the queue
# Each extra comparison that fires raises the priority score by this share.
AGREEMENT_BONUS = 0.25

# --- Data completeness --------------------------------------------------------
# Admissions older than this are treated as fully reported.
COMPLETENESS_HORIZON_DAYS = 150
# Never scale a day's count up by more than 1 / this.
COMPLETENESS_FLOOR = 0.25

# --- Diagnosis code breakdown -------------------------------------------------
# Codes shown when a diagnosis group is opened. Detection never uses them.
TOP_CODES = 5
# A slice needs this many admissions in the past year to supply its own "usual"
# mix of codes. Smaller slices borrow the plan-wide mix for that diagnosis group.
CODE_HISTORY_MIN = 30

# --- AI summary ---------------------------------------------------------------
# Used only when the ANTHROPIC_API_KEY environment variable is set.
SUMMARY_MODEL = "claude-haiku-4-5-20251001"

# --- What's driving it (part two) ---------------------------------------------
# Fixed rules shortlist outside items and set the strength labels; those rules
# and their thresholds are at the top of clinical_signal/causes.py. Claude then
# reads the shortlisted items and writes the explanations. Used only when the
# ANTHROPIC_API_KEY environment variable is set; standard wording otherwise.
CAUSE_MODEL = "claude-sonnet-5-5"

# --- Who can act (part three) ---------------------------------------------------
# The owner and the recommendation come from data/action_mapping.csv by fixed rules
# (clinical_signal/actions.py). Claude only rewords a recommended action for the
# hotspot and drafts the hand-off message, and only when ANTHROPIC_API_KEY is set.
ACTION_MODEL = "claude-sonnet-5-5"
