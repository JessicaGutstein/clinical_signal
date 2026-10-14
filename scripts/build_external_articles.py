"""Turns each outside item into a page that opens like an article.

    python scripts/build_external_articles.py

Reads external_data/outside_signals.csv and writes, into external_data/:

    articles/S001.html ...   one page per outside item
    index.html               a list of every item, with a search box

The pages stand in for the links a real version would follow to a news site, a
health department notice, or a weather bulletin. Everything in them is invented.
Each page says so at the top.

The headline and the first paragraph are the item's title and text exactly as
they are in the CSV, which is what the matching rules and Claude read. A few
items that matter most on the dashboard have two more paragraphs, held in MORE
below. Those paragraphs add colour only: no hospital is named, and nothing in
them is used for matching.

No page names a hospital or a health system, and none shows which facility an
item is tied to. The pages are fixed: the same CSV always gives the same pages.
"""

from __future__ import annotations

import csv
import html
from datetime import date
from pathlib import Path

EXTERNAL_DIR = Path(__file__).resolve().parents[1] / "external_data"
ARTICLES_DIR = EXTERNAL_DIR / "articles"
SIGNALS_FILE = "outside_signals.csv"

SOURCE_TYPES = {
    "public_health": "Public health notice",
    "weather_air": "Weather and air quality",
    "news": "Local news",
    "facility_event": "Facility or network event",
}

# Two more paragraphs for the items that lead a possible cause today, keyed by title.
MORE = {
    "Inspection finds catheter-care lapses at three Manhattan nursing homes": [
        "Inspectors found that catheters were left in place longer than care plans called for, and that staff did not always record when one was changed. Both raise the risk of urinary tract infection, which in frail residents can spread to the bloodstream.",
        "The department said it will inspect the homes again at the end of the correction period. Families with concerns can ask a home for its most recent inspection report.",
    ],
    "Pharmacy chain closes four stores in the Bronx": [
        "The company said the stores were closed as part of a wider review and that prescriptions were transferred automatically to its remaining locations. Customers were sent letters with the new address.",
        "A tenants' association in the area said many older residents do not drive, and that the nearest remaining store is two bus rides away for some of them. It has asked the chain to offer home delivery.",
    ],
    "Community diabetes clinic in Morris Park closes in consolidation": [
        "The clinic's operator said combining two sites would let it keep specialist nurses and a foot-care service that neither site could staff alone. Existing patients were sent letters with their new appointment details.",
        "Diabetes educators say gaps in routine visits are when problems build: blood sugar goes unchecked, insulin doses are not adjusted, and foot wounds are missed. Patients who run into trouble during a gap often end up at the closest emergency department.",
    ],
    "Dialysis provider closes two Upper East Side clinics": [
        "Most people on dialysis need treatment three times a week, for several hours each time. The company said it was helping patients transfer, but some said they had not yet been given a regular slot elsewhere.",
        "Patient advocates said the remaining clinics in Manhattan were already close to full, and that evening sessions, which working patients depend on, are the hardest to find.",
    ],
    "Ambulances to take suspected stroke patients to newly designated stroke centers from September 1": [
        "Before the change, crews took most suspected stroke patients to the nearest emergency department. The council said the new rule is meant to get patients to hospitals that can offer specialist stroke treatment without a second transfer.",
        "The council expects stroke admissions to rise at the designated centers and to fall at the hospitals that used to receive those patients. It said the total number of strokes in the region is not expected to change.",
    ],
    "Hospital in southeast Brooklyn closes its maternity and inpatient cardiac units": [
        "The hospital told the department it could no longer staff the two units safely. Its emergency department and outpatient clinics remain open.",
        "Ambulance services were told to take women in labor and patients with heart conditions to other hospitals from the date of the closure. The department said it would monitor waiting times at the hospitals taking the extra patients.",
    ],
    "Nassau County moves its employees and retirees to a new health plan": [
        "The county legislature approved the change earlier in the year after a competitive bid. Members keep their existing doctors where those doctors are in the new plan's network.",
        "The change means the new plan has more members living in Nassau County than it did in August. Hospital stays by those members now appear in the new plan's figures, without any change in how often they need care.",
    ],
    "Late-summer heat advisory for the whole region": [
        "Overnight temperatures stayed warm through the period, which gives little relief to people without air conditioning. Cooling centers were opened across the region.",
        "The service advised checking on older neighbors and relatives, drinking water regularly, and avoiding outdoor work in the afternoon. Temperatures returned to normal after the advisory ended.",
    ],
    "Outpatient infusion clinic on the Upper East Side closes after water damage": [
        "The clinic gives chemotherapy and other infusions to patients who would otherwise go home the same day. The notice says no patients were harmed and that treatment schedules are being kept.",
        "Because the receiving hospital does not have spare outpatient infusion chairs, it is admitting the referred patients for each treatment. The department said this arrangement will end when the clinic reopens.",
    ],
    "Respiratory illness level in Queens moves to High, weeks earlier than usual": [
        "The level is based on the share of visits to clinics and emergency departments that are for fever with a cough or sore throat. A move to High this early in September has not been recorded in recent seasons.",
        "The department advised residents to get this season's flu vaccine as soon as it is available to them, and asked clinics in Queens to report unusual clusters.",
    ],
    "Brooklyn public hospital feels the strain after neighbour shuts units": [
        "Nurses on the maternity floor said they have been working extra shifts to cover the additional deliveries. A cardiologist said the heart unit has been close to full on most days.",
        "The hospital said it is caring for every patient who arrives and has asked for temporary staff. It did not say how long it expects the extra demand to last.",
    ],
    "Air quality alert for the Bronx: fine particles unhealthy for sensitive groups": [
        "Fine particles are small enough to reach deep into the lungs. On alert days, people with asthma or chronic lung disease are more likely to have flare-ups that need emergency care, and the effect can last for several days after levels fall.",
        "The bulletin advised keeping windows closed, using rescue inhalers as prescribed, and seeking care early if breathing gets worse.",
    ],
    "Nurses strike at a Bergen County hospital; ambulances diverted to Hackensack": [
        "The union said the walkout is over staffing levels. The hospital said it had brought in temporary nurses to care for patients already admitted, but could not safely accept new ones.",
        "Emergency crews said the diversion will continue until the strike ends.",
    ],
    "Enterovirus D68 found in Queens schoolchildren; asthma flare-ups expected": [
        "Enterovirus D68 spreads like a cold. Most children recover without treatment, but those with asthma can become seriously short of breath within a day or two.",
        "The department asked parents of children with asthma to make sure controller medicines are being taken and that a rescue inhaler is on hand, and to seek care quickly if a child is struggling to breathe.",
    ],
    "Queens schools report early wave of flu absences": [
        "One principal said attendance in some classes was noticeably down. School nurses said most children were back within a week.",
        "Doctors' offices in the area said they were seeing whole families with the same symptoms, and that some older relatives had needed hospital care.",
    ],
    "Queens respiratory illness level stays High for a third week": [
        "The department said the rise has spread from central and eastern Queens to the rest of the borough. Levels in the other boroughs have started to rise but remain Low.",
        "Older adults and people with heart or lung conditions are most at risk of needing hospital care. The department repeated its advice to get vaccinated.",
    ],
    "Second air quality alert in two weeks for the Bronx": [
        "Two alerts this close together are unusual for September. The bulletin says people with asthma or chronic lung disease may not have fully recovered from the first episode before the second began.",
        "Air quality is expected to improve as winds pick up. The same advice applies as during the first alert.",
    ],
    "Stomach illness cluster linked to a street festival in Sunset Park": [
        "Symptoms began within a day or two of the festival and most people recovered at home. Those who needed hospital care were mainly treated for dehydration.",
        "The department is interviewing people who became ill and testing food samples. It asked anyone who ate at the festival and became sick to report it.",
    ],
}

CSS = """
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:#f4f5f2;color:#14212d;font:17px/1.6 "Atkinson Hyperlegible Next","Segoe UI",system-ui,-apple-system,sans-serif}
a{color:#2c6a0f;text-underline-offset:3px}
a:focus-visible,input:focus-visible{outline:3px solid #2c6a0f;outline-offset:2px}
.demo{background:#14212d;color:#fff;font-size:14px;line-height:1.45;padding:10px 16px;text-align:center}
.demo b{font-weight:700}
.wrap{max-width:720px;margin:0 auto;padding:0 16px 56px}
.back{display:inline-block;margin:18px 0 14px;font-size:15px}
.sheet{background:#fff;border:1px solid #dde4e0;border-radius:10px;overflow:hidden}
.mast{padding:18px 28px;border-bottom:1px solid #dde4e0}
.mast .name{font-size:24px;font-weight:700;line-height:1.2}
.mast .kind{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:#47586a;margin-top:4px}
.news .mast{text-align:center;border-bottom:3px double #14212d}
.news .mast .name{font-family:Georgia,"Times New Roman",serif;font-size:30px;font-weight:700}
.notice .mast{background:#eef2f5;border-left:6px solid #47586a}
.bulletin .mast{background:#eaf2f8;border-left:6px solid #3d6c8f}
.body{padding:26px 28px 30px}
h1{font-size:30px;line-height:1.22;margin:0 0 12px;text-wrap:balance}
.news h1{font-family:Georgia,"Times New Roman",serif;font-size:34px}
.by{font-size:14.5px;color:#47586a;margin:0 0 20px;padding-bottom:16px;border-bottom:1px solid #dde4e0}
.body p{margin:0 0 16px}
.news .body p{font-family:Georgia,"Times New Roman",serif;font-size:18.5px;line-height:1.65}
.news .body p.by{font-family:inherit;font-size:14.5px;line-height:1.5}
.facts{margin:24px 0 0;padding:0;border-top:1px solid #dde4e0}
.facts div{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px;padding:9px 0;border-bottom:1px solid #dde4e0;font-size:15px}
.facts dt{color:#47586a}
.facts dd{margin:0}
.tags{margin-top:20px;background:#fff;border:1px dashed #6b7986;border-radius:10px;padding:18px 28px 8px}
.tags h2{font-size:16px;margin:0 0 6px}
.tags p{font-size:14.5px;color:#47586a;margin:0 0 8px}
.tags .facts{margin-top:10px}
.tags .facts div:last-child{border-bottom:0}
.lede{font-size:16px;color:#47586a;margin:0 0 18px}
.search{width:100%;font:inherit;padding:10px 12px;border:1px solid #6b7986;border-radius:8px;margin:0 0 6px}
.count{font-size:14px;color:#47586a;margin:0 0 18px}
h2.sec{font-size:19px;margin:28px 0 8px}
.list{list-style:none;margin:0;padding:0;background:#fff;border:1px solid #dde4e0;border-radius:10px}
.list li{padding:11px 18px;border-bottom:1px solid #dde4e0}
.list li:last-child{border-bottom:0}
.list a{font-weight:700;font-size:16px;line-height:1.35}
.list span{display:block;font-size:14px;color:#47586a}
.list .flag{display:inline;font-size:12.5px;font-weight:700;color:#14212d;border:1px solid #6b7986;border-radius:999px;padding:1px 8px;margin-left:6px;white-space:nowrap}
[hidden]{display:none!important}
@media (max-width:520px){.mast,.body,.tags{padding-left:18px;padding-right:18px}h1,.news h1{font-size:26px}.facts div{grid-template-columns:1fr;gap:0}}
"""

BANNER = ('<div class="demo" role="note"><b>Made up for the Clinical Signal prototype.</b> '
          "This is not a real article. The source, the events and every figure are invented.</div>")


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def clean_source(name: str) -> str:
    """'City health department (invented notice)' -> 'City health department'. The banner says it is invented."""
    return name.split(" (invented")[0].strip()


def layout(row: dict) -> str:
    if row["source_type"] == "weather_air":
        return "bulletin"
    return "notice" if "(invented" in row["source_name"] else "news"


def covers(row: dict) -> str:
    if row["ends"] and row["ends"] != row["starts"]:
        return f"{long_date(row['starts'])} to {long_date(row['ends'])}"
    if row["starts"] != row["published"]:
        return f"From {long_date(row['starts'])}"
    return f"From {long_date(row['starts'])}" if not row["ends"] else long_date(row["starts"])


def area_text(row: dict) -> str:
    areas = [a.strip() for a in row["areas"].split(";") if a.strip()]
    if not areas:
        return "Several areas (see the text)"
    return "The whole region" if areas == ["All"] else ", ".join(areas)


def page(title: str, body: str, cls: str = "") -> str:
    return (f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f'<meta name="robots" content="noindex">\n<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n'
            f'<body class="{cls}">\n{BANNER}\n<div class="wrap">\n{body}\n</div>\n</body>\n</html>\n')


def article(row: dict) -> str:
    kind = layout(row)
    source = clean_source(row["source_name"])
    label = SOURCE_TYPES.get(row["source_type"], "Outside source")
    if kind == "news":
        by = f"Staff report &middot; {long_date(row['published'])}"
    else:
        by = f"{'Bulletin' if kind == 'bulletin' else 'Notice'} {esc(row['item_id'])} &middot; Issued {long_date(row['published'])}"
    paragraphs = [row["body"]] + MORE.get(row["title"], [])
    text = "\n".join(f"<p>{esc(p)}</p>" for p in paragraphs)
    related = "; ".join(x for x in (row["diagnosis_direct"], row["diagnosis_indirect"]) if x) or "None"
    cause = "None (unrelated to admissions)" if row["topic"] == "unrelated" else row["topic"].replace("_", " ").capitalize()
    level = {"routine": "Routine: reports nothing unusual", "background": "Background: a trend with no dates",
             "notable": "Notable: reports something out of the ordinary"}.get(row["level"], row["level"])
    body = f"""<a class="back" href="../index.html">&larr; All outside items</a>
<article class="sheet {kind}">
<header class="mast"><div class="name">{esc(source)}</div><div class="kind">{esc(label)}</div></header>
<div class="body">
<h1>{esc(row['title'])}</h1>
<p class="by">{by}</p>
{text}
<dl class="facts">
<div><dt>Area</dt><dd>{esc(area_text(row))}</dd></div>
<div><dt>Dates it covers</dt><dd>{esc(covers(row))}</dd></div>
<div><dt>Published</dt><dd>{long_date(row['published'])}</dd></div>
</dl>
</div>
</article>
<section class="tags" aria-labelledby="tags-h">
<h2 id="tags-h">How Clinical Signal reads this item</h2>
<p>Item {esc(row['item_id'])}. These labels are what the matching rules use. In this prototype they were written by hand; a real version would need a step that reads each article and fills them in.</p>
<dl class="facts">
<div><dt>Kind of cause</dt><dd>{esc(cause)}</dd></div>
<div><dt>Related diagnoses</dt><dd>{esc(related)}</dd></div>
<div><dt>Who it affects</dt><dd>{esc('Children' if row['population'] == 'children' else 'Everyone')}</dd></div>
<div><dt>Kind of report</dt><dd>{esc(level)}</dd></div>
</dl>
</section>"""
    return page(f"{row['title']} | {source}", body)


def index(rows: list[dict]) -> str:
    sections = []
    for key, label in SOURCE_TYPES.items():
        mine = sorted((r for r in rows if r["source_type"] == key), key=lambda r: (r["published"], r["item_id"]), reverse=True)
        if not mine:
            continue
        lis = "\n".join(
            f'<li><a href="articles/{esc(r["item_id"])}.html">{esc(r["title"])}</a>'
            f'{"" if r["level"] == "routine" else " <span class=flag>Notable</span>" if r["level"] == "notable" else " <span class=flag>Background</span>"}'
            f'<span>{esc(clean_source(r["source_name"]))} &middot; {long_date(r["published"])} &middot; {esc(area_text(r))}</span></li>'
            for r in mine)
        sections.append(f'<section data-sec><h2 class="sec">{esc(label)} ({len(mine)})</h2>\n<ul class="list">\n{lis}\n</ul></section>')
    body = f"""<h1 style="margin-top:28px">Outside items</h1>
<p class="lede">{len(rows)} invented notices, bulletins and news stories from outside the health plan. Clinical Signal reads these, and nothing else, when it looks for what may be driving a hotspot. In a real version each would be a link to the source's own website.</p>
<label for="q" class="count" style="display:block;margin-bottom:6px">Search titles, sources and areas</label>
<input class="search" id="q" type="search" autocomplete="off">
<p class="count" id="n" aria-live="polite">Showing all {len(rows)} items, newest first in each group.</p>
{chr(10).join(sections)}
<script>
const q=document.getElementById('q'),n=document.getElementById('n'),items=[...document.querySelectorAll('.list li')];
q.addEventListener('input',()=>{{const t=q.value.trim().toLowerCase();let c=0;
items.forEach(li=>{{const on=!t||li.textContent.toLowerCase().includes(t);li.hidden=!on;if(on)c++;}});
document.querySelectorAll('[data-sec]').forEach(s=>{{s.hidden=!s.querySelector('li:not([hidden])');}});
n.textContent=t?`Showing ${{c}} of ${{items.length}} items.`:`Showing all ${{items.length}} items, newest first in each group.`;}});
</script>"""
    return page("Outside items | Clinical Signal prototype", body)


def main() -> None:
    with open(EXTERNAL_DIR / SIGNALS_FILE, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    missing = sorted(set(MORE) - {r["title"] for r in rows})
    if missing:
        raise SystemExit(f"Extra paragraphs have no matching item: {missing}")
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    for r in rows:
        (ARTICLES_DIR / f"{r['item_id']}.html").write_text(article(r), encoding="utf-8")
    (EXTERNAL_DIR / "index.html").write_text(index(rows), encoding="utf-8")
    print(f"Wrote {len(rows)} article pages and index.html into {EXTERNAL_DIR}")


if __name__ == "__main__":
    main()
