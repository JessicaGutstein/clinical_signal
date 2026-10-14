"""Checks that the dashboard shows what detection found, and is laid out as designed.

    python tests/dashboard_checks.py [results.json]

The app must already be running at http://127.0.0.1:5050. This drives a real
browser through every hotspot and several facilities and compares what is on the
screen with what detection computed. It needs the `playwright` package and a
Chromium browser, which the app itself does not need, so it is run during testing
and its results are recorded in the evaluation log.

Set AXE_JS to the path of axe.min.js to include the accessibility scan.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from clinical_signal.data_loader import load  # noqa: E402
from clinical_signal.detection.engine import Engine, public  # noqa: E402

URL = "http://127.0.0.1:5050/"
results: list[dict] = []


def record(cid: str, what: str, ok: bool, detail: str = "") -> None:
    results.append({"id": cid, "what": what, "passed": bool(ok), "detail": detail})
    print(f"{'PASS' if ok else 'FAIL'}  {cid:<4} {what}{'  [' + detail + ']' if detail else ''}")


def money(n: float) -> str:
    if n >= 1e6:
        return f"${n / 1e6:.1f}M"
    if n >= 1e3:
        return f"${round(n / 1e3)}K"
    return f"${round(n)}"


def signed(n: int) -> str:
    return f"+{n:,}" if n > 0 else f"−{abs(n):,}" if n < 0 else "0"


LIST_JS = """() => [...document.querySelectorAll('#queue .q-item')].map(b => ({
  id: b.dataset.alert, rank: b.querySelector('.badge.rank').lastChild.textContent.trim(),
  title: b.querySelector('.q-title').textContent.trim(),
  count: b.querySelector('.q-count').childNodes[0].textContent.trim(),
  vs: b.querySelector('.q-vs').textContent.trim(), selected: b.classList.contains('is-selected')}))"""


async def main(out_path: str | None) -> int:
    from playwright.async_api import async_playwright

    ds = load()
    det = Engine(ds).run("all")
    alerts = [public(a) for a in det.alerts]
    high = [a for a in alerts if a["priority"] == "high"]
    low = [a for a in alerts if a["priority"] == "low"]
    fac_by_id = {f["id"]: f for f in det.facilities}

    # ---- Counts are real: straight from the admissions file, nothing added ----
    adm = pd.read_csv(config.DATA_DIR / "synthetic_admissions.csv", usecols=["facility_id", "admit_date"], parse_dates=["admit_date"])
    start = pd.Timestamp(ds.as_of) - pd.Timedelta(days=config.WINDOW_DAYS - 1)
    in_window = adm[adm["admit_date"] >= start]
    per_hospital = in_window.groupby("facility_id").size()
    wrong = [f["name"] for f in det.facilities if f["display"]["observed"] != int(per_hospital.get(f["id"], 0))]
    record("C1", "Every facility's count equals the member admissions reported in the data file (100 facilities)", not wrong,
           f"{len(det.facilities) - len(wrong)} of {len(det.facilities)} match")

    axe_js = Path(os.environ["AXE_JS"]).read_text() if os.environ.get("AXE_JS") else None
    axe_found: dict[str, list] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        errors: list[str] = []
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        async def axe(name: str) -> None:
            if not axe_js:
                return
            await page.evaluate(axe_js)
            r = await page.evaluate("axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}})")
            if r["violations"]:
                axe_found[name] = [f"{v['id']} ({len(v['nodes'])})" for v in r["violations"]]

        await page.goto(URL)
        await page.wait_for_selector(".q-item")
        await page.wait_for_timeout(800)
        body = await page.inner_text("body")

        # ---- Titles, name, and what was removed ----
        titles = await page.evaluate("[...document.querySelectorAll('.p-title h2')].map(h => h.textContent.trim())")
        record("L1", "Each panel has its title: Top hotspots, Map, Summary", titles == ["Top hotspots", "Map", "Summary"], ", ".join(titles))
        brand = await page.inner_text(".brand")
        record("L2", "The app is named Humana Clinical Signal, marked Prototype", "Humana Clinical Signal" in brand and "Prototype" in brand)
        record("L3", "Line of business is gone from the screen", "Line of business" not in body and await page.locator("select").count() == 0)
        top_bar = await page.inner_text("#asof")
        record("C2", "The top bar total equals the admissions reported in the window", f"{len(in_window):,}" in top_bar, top_bar)
        await axe("plan summary")

        # ---- The left list ----
        rows = await page.evaluate(LIST_JS)
        want = [(str(a["rank"]), a["title"], f"{a['display']['observed']:,}", f"vs {a['display']['expected']:,} expected") for a in high]
        got = [(r["rank"], r["title"], r["count"], r["vs"]) for r in rows]
        record("L4", f"The list shows the top hotspots in rank order, each with reported vs expected ({len(high)} rows)", got == want)
        record("L5", "The list has no '+N above expected' figure; that is on the right", not re.search(r"[+]\d", await page.inner_text("#queue")))
        if low:
            await page.click("[data-more]")
            await page.wait_for_timeout(200)
            rows_all = await page.evaluate(LIST_JS)
            record("L6", f"The drop-down shows the remaining hotspots ({len(low)})", [r["id"] for r in rows_all] == [a["id"] for a in alerts])
        list_html = await page.inner_html("#queue")

        tabs_plan = await page.evaluate("[...document.querySelectorAll('#detail [role=tab]')].map(t => t.textContent.trim())")
        TABS = ["Detected", "What’s driving it", "Who can act"]

        # ---- Every hotspot: the right side against detection ----
        bad_excess, bad_cost, bad_checks, bad_dupe, bad_tabs, bad_list, bad_summary = [], [], [], [], [], [], []
        for a in alerts:
            await page.click(f'[data-alert="{a["id"]}"]')
            await page.wait_for_function("!document.querySelector('[data-summary] .loading')")
            d = a["display"]
            info = await page.evaluate("""() => ({
              excess: document.querySelector('.fig-num.red').textContent.trim(),
              cost: document.querySelectorAll('.fig-num')[1].textContent.trim(),
              marks: [...document.querySelectorAll('.checks .check')].map(c => c.classList.contains('is-on')),
              tabs: [...document.querySelectorAll('#detail [role=tab]')].map(t => t.textContent.trim()),
              visible: (() => { const c = document.querySelector('#panel-detected').cloneNode(true); c.querySelectorAll('.tip, .sr, details').forEach(n => n.remove()); return c.textContent; })(),
              summary: document.querySelector('[data-summary]').textContent.trim(),
              selected: [...document.querySelectorAll('#queue .q-item.is-selected')].map(b => b.dataset.alert)})""")
            if info["excess"] != signed(d["excess"]):
                bad_excess.append(a["id"])
            if info["cost"] != money(a["excess_spend"]):
                bad_cost.append(a["id"])
            if info["marks"] != [c["fired"] for c in a["comparisons"]]:
                bad_checks.append(a["id"])
            if f"{d['observed']} vs" in info["visible"] or "vs " + str(d["expected"]) + " expected" in info["visible"]:
                bad_dupe.append(a["id"])
            if info["tabs"] != TABS:
                bad_tabs.append(a["id"])
            if info["selected"] != [a["id"]]:
                bad_list.append(a["id"])
            if "than usual" not in info["summary"]:
                bad_summary.append(a["id"])
        n = len(alerts)
        record("R1", f"'+N above expected' equals reported minus expected, for every hotspot ({n})", not bad_excess, ", ".join(bad_excess))
        record("R2", f"The estimated extra cost matches detection, for every hotspot ({n})", not bad_cost, ", ".join(bad_cost))
        record("R3", f"The four check marks match the four comparisons, for every hotspot ({n})", not bad_checks, ", ".join(bad_checks))
        record("R4", f"'Reported vs expected' is not repeated on the right, for every hotspot ({n})", not bad_dupe, ", ".join(bad_dupe))
        record("R5", "The three tabs are present for the plan and for every hotspot", tabs_plan == TABS and not bad_tabs)
        record("R6", f"Every hotspot has a plain-language summary ({n})", not bad_summary, ", ".join(bad_summary))
        record("L7", "Selecting a hotspot only highlights its row; the list is otherwise unchanged", not bad_list)

        # ---- One hotspot in depth: explanations, drop-downs, chart ----
        wave = next((a for a in alerts if a["kind"] == "wave"), alerts[0])
        await page.click(f'[data-alert="{wave["id"]}"]')
        await page.wait_for_function("!document.querySelector('[data-summary] .loading')")
        await axe("hotspot")
        await page.locator(".fig .tip-btn").first.hover()
        tip = await page.locator(".fig .tip").first.inner_text()
        d = wave["display"]
        shown = await page.locator(".fig .tip").first.is_visible()
        record("R7", "Hovering '+N' explains how it was worked out, with the real numbers", shown and str(d["observed"]) in tip and str(d["expected"]) in tip, tip[:90])
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(150)
        hidden = not await page.locator(".fig .tip").first.is_visible()
        still = await page.locator(f'#queue .q-item.is-selected[data-alert="{wave["id"]}"]').count() == 1
        record("R8", "Escape closes an explanation without losing the selection", hidden and still)
        await page.mouse.move(700, 300)
        await page.locator(".check .tip-btn").first.focus()
        record("R9", "Explanations also open from the keyboard (tab to a line)", await page.locator(".check .tip").first.is_visible())
        drops = await page.evaluate("[...document.querySelectorAll('#panel-detected details.drop')].map(d => [d.dataset.drop, d.open])")
        record("R10", "Detail sits in drop-downs that start closed: facilities, codes, chart",
               [x[0] for x in drops] == ["members", "codes", "chart"] and not any(x[1] for x in drops), str(drops))
        await page.click('details[data-drop="codes"] > summary')
        await page.wait_for_selector(".code-row")
        codes = await page.evaluate("[...document.querySelectorAll('.code-row .tip-btn')].map(b => [b.querySelector('.code').textContent, +b.querySelector('.code-n').textContent])")
        known = pd.read_csv(config.DATA_DIR / "icd10_codes.csv")
        group_of = dict(zip(known["code"], known["diagnosis_group"]))
        record("R11", "Top diagnosis codes all belong to the hotspot's diagnosis group, at most five",
               0 < len(codes) <= config.TOP_CODES and all(group_of.get(c) == wave["diagnosis"] for c, _ in codes), ", ".join(c for c, _ in codes))
        await page.click('details[data-drop="chart"] > summary')
        await page.wait_for_selector(".chart svg")
        chart = await page.evaluate("""() => ({title: document.querySelector('.chart-title').textContent,
          axes: [...document.querySelectorAll('.chart .axis-title')].map(t => t.textContent),
          band: document.querySelector('.chart .band-label')?.textContent, recent: !!document.querySelector('.chart path.recent'),
          recentColor: getComputedStyle(document.querySelector('.chart path.recent')).stroke,
          historyColor: getComputedStyle(document.querySelector('.chart path.history')).stroke,
          note: document.querySelector('.chart-note').textContent})""")
        record("R12", "The chart has a title naming the diagnosis and place", wave["title"] in chart["title"] and wave["subtitle"] in chart["title"], chart["title"])
        record("R13", "Both chart axes are labelled", chart["axes"] == ["Member admissions per week", "Month (past 12 months)"], str(chart["axes"]))
        record("R14", "The band is labelled 'Normal range' on the chart and explained under it", chart["band"] == "Normal range" and "normal range" in chart["note"])
        record("R15", "The last four weeks are a red line; the history is grey", chart["recent"] and chart["recentColor"] == "rgb(199, 46, 43)" and chart["historyColor"] != chart["recentColor"])
        await axe("hotspot, drop-downs open")

        # Tabs
        await page.click("#tab-cause")
        await page.wait_for_selector("#panel-cause .causes, #panel-cause .none-found")
        cause = await page.inner_text("#panel-cause")
        await page.keyboard.press("ArrowRight")
        action = await page.inner_text("#panel-action")
        focus = await page.evaluate("document.activeElement.id")
        record("R16", "The second tab shows possible causes; the third says who can act and is no longer reserved; arrow keys move between tabs",
               "possible cause" in cause and "Next phase" not in action and ("Needs analyst review" in action or "recommendation" in action) and focus == "tab-action")
        await axe("reserved tab")

        # ---- Part two: what's driving it ----
        # The tab must show exactly what the rules found for this hotspot, with its evidence,
        # and nothing may count as confirmed until a person presses Confirm.
        await page.click("#tab-cause")
        found = await (await page.context.request.get(URL + f"api/alerts/{wave['id']}/causes")).json()
        shown = await page.evaluate("""() => [...document.querySelectorAll('#panel-cause .cause')].map(c => ({
          label: c.querySelector('h5').textContent.replace(/^Possible cause \\d+: /, ''),
          strength: c.querySelector('.strength-word').textContent,
          bars: c.querySelectorAll('.strength-bars i.on').length,
          items: c.querySelectorAll('.src a.src-title').length,
          status: c.querySelector('.rv-status').textContent.trim()}))""")
        want = [(c["label"], c["strength"].capitalize() + " match", {"strong": 3, "moderate": 2, "weak": 1}[c["strength"]], len(c["items"])) for c in found["causes"]]
        record("D1", "The tab lists the possible causes the rules found, in the same order, with the same strength",
               [(c["label"], c["strength"], c["bars"], c["items"]) for c in shown] == want and len(want) > 0, str([c["label"] for c in shown]))
        record("D2", "Strength is told by a word and by filled bars, and nothing on the tab is red",
               all(c["bars"] in (1, 2, 3) for c in shown) and not await page.evaluate(
                   "[...document.querySelectorAll('#panel-cause *')].some(e => [getComputedStyle(e).color, getComputedStyle(e).backgroundColor].includes('rgb(199, 46, 43)'))"))
        # Each outside item is a link to its own page, which carries the item's title and full text.
        first = found["causes"][0]["items"][0]
        link = await page.evaluate("(() => { const a = document.querySelector('#panel-cause .src a.src-title'); return {href: a.getAttribute('href'), target: a.target, text: a.textContent}; })()")
        article = await (await page.context.request.get(URL.rstrip("/") + link["href"])).text()
        import html as _html
        record("D3", "Each outside item is a link that opens its own page, with the full text of the item",
               link["href"] == first["url"] and link["target"] == "_blank" and first["title"] in link["text"]
               and _html.escape(first["title"]) in article and _html.escape(first["body"]) in article and "Made up for the Clinical Signal prototype" in article)
        await page.focus("#panel-cause .strength .tip-btn")
        tip = await page.inner_text("#cause-tip-0")
        record("D4", "The strength can be opened by keyboard to show the place, timing and diagnosis tests", all(w in tip for w in ("Place", "Timing", "Diagnosis")))
        record("D5", "Every possible cause starts as 'Not reviewed yet'", all("Not reviewed yet" in c["status"] for c in shown), str([c["status"][:20] for c in shown]))
        await page.fill("#rv-name", "Dashboard check")
        await page.click("#panel-cause .rv [data-review=confirmed]")
        await page.wait_for_selector("#panel-cause .rv-status.is-confirmed")
        status = await page.inner_text("#panel-cause .rv-status.is-confirmed")
        saved = await (await page.context.request.get(URL + f"api/alerts/{wave['id']}/causes")).json()
        focused = await page.evaluate("document.activeElement.dataset.review")
        record("D6", "Confirm records who decided, is saved, and keeps keyboard focus on the button",
               "Confirmed by Dashboard check" in status and saved["confirmed"] == [found["causes"][0]["label"]] and focused == "confirmed", status)
        await axe("what's driving it")

        # ---- Part three: who can act ---- (the cause above is confirmed at this point)
        await page.click("#tab-action")
        await page.wait_for_selector("#panel-action .act")
        acts = await (await page.context.request.get(URL + f"api/alerts/{wave['id']}/actions")).json()
        rec = acts["recommendations"][0]
        panel = await page.inner_text("#panel-action")
        record("E1", "A confirmed cause gets the owner and the recommendation the mapping gives, marked as a draft",
               rec["owner"] in panel and rec["text"] in panel and "Draft" in panel, rec["owner"])
        await page.click("#panel-action [data-act=accepted]")
        await page.wait_for_selector("#panel-action [data-ho-body]")
        message = await page.input_value("#panel-action [data-ho-body]")
        to = await page.inner_text("#panel-action .ad-to")
        record("E2", "Accepting shows a hand-off message to the plan team's contact, for a person to send",
               rec["cause"]["label"] in message and rec["contact_role"] in to, to)
        await axe("who can act")
        await page.click("#panel-action [data-act=undo]")
        await page.wait_for_selector("#panel-action [data-act=accepted]")
        await page.click("#tab-cause")
        await page.click("#panel-cause .rv [data-review=confirmed]")   # pressing it again clears the decision
        await page.wait_for_selector("#panel-cause .rv-status:not(.is-confirmed)")
        cleared = await (await page.context.request.get(URL + f"api/alerts/{wave['id']}/causes")).json()
        record("D7", "Pressing the chosen button again clears the decision", cleared["confirmed"] == [])
        acts = await (await page.context.request.get(URL + f"api/alerts/{wave['id']}/actions")).json()
        record("E3", "With no confirmed cause there is no recommendation, only 'Needs analyst review'",
               acts["recommendations"] == [] and acts["default"]["owner"] == "Clinical analytics")
        no_cause = None
        for a in alerts:
            if not (await (await page.context.request.get(URL + f"api/alerts/{a['id']}/causes")).json())["causes"]:
                no_cause = a
                break
        if no_cause:
            if await page.query_selector(".q-more > button[aria-expanded=false]"):
                await page.click(".q-more > button")
            await page.click(f'[data-alert="{no_cause["id"]}"]')
            await page.click("#tab-cause")
            await page.wait_for_selector("#panel-cause .none-found")
            text = await page.inner_text("#panel-cause")
            record("D8", "A hotspot with nothing behind it says 'No outside explanation found' and offers no buttons",
                   "No outside explanation found" in text and not await page.query_selector("#panel-cause [data-review]"), no_cause["id"])
            await axe("no outside explanation")
            await page.click(f'[data-alert="{wave["id"]}"]')
            await page.wait_for_timeout(300)
        await page.click("#tab-detected")

        # ---- Hospitals: the list on the left must not change ----
        await page.click("[data-close]")
        await page.wait_for_timeout(200)
        before = await page.inner_html("#queue")
        sample = [f for f in det.facilities if f["high_alerts"] or f["low_alerts"]] + [f for f in det.facilities if not (f["high_alerts"] or f["low_alerts"])][:6]
        await page.click('[data-mode="table"]')
        bad_cards, bad_count, changed, bad_facts, bad_members, bad_label = [], [], [], [], [], []
        fac_file = pd.read_csv(config.DATA_DIR / "facilities.csv", dtype=str).set_index("facility_id")
        for f in sample:
            await page.click(f'#maptable [data-facility="{f["id"]}"]')
            await page.wait_for_timeout(120)
            got = await page.evaluate("""() => ({cards: [...document.querySelectorAll('#detail .card')].map(c => [c.dataset.alert, c.querySelector('.card-num').textContent.trim()]),
              count: document.querySelector('#detail .fig-num').textContent.trim(), kind: document.querySelector('#detail .p-title p').textContent,
              tabs: [...document.querySelectorAll('#detail [role=tab]')].map(t => t.textContent.trim())})""")
            want_ids = f["high_alerts"] + f["low_alerts"]
            if [c[0] for c in got["cards"]] != want_ids or got["tabs"] != []:   # a facility summary has no tabs
                bad_cards.append(f["name"])
            if got["count"] != f"{f['display']['observed']:,}":
                bad_count.append(f["name"])
            if await page.inner_html("#queue") != before:
                changed.append(f["name"])
            facts = await page.evaluate("Object.fromEntries([...document.querySelectorAll('#detail .facts > div')].map(d => [d.querySelector('dt').textContent.trim(), d.querySelector('dd').textContent.trim()]))")
            row = fac_file.loc[f["id"]]
            if (facts.get("Type of facility"), facts.get("Health system"), facts.get("Network status")) != (row["facility_type"], row["health_system"], row["network_status"]):
                bad_facts.append(f["name"])
            m = ds.membership[f["area"]]
            if not facts.get(f"Members living in {f['area']}", "").startswith(f"{m['members']:,}"):
                bad_members.append(f["name"])
            label = await page.evaluate("document.querySelector('#detail .fig-label').textContent")
            if "member admissions" not in label:
                bad_label.append(f["name"])
        record("H1", f"Clicking a facility never changes or filters the list on the left ({len(sample)} facilities)", not changed, ", ".join(changed[:3]))
        record("H2", f"The facility summary lists exactly the hotspots at that facility, as cards ({len(sample)} facilities)", not bad_cards, ", ".join(bad_cards[:3]))
        record("H3", f"The facility's member admissions figure matches the data ({len(sample)} facilities)", not bad_count, ", ".join(bad_count[:3]))
        record("F1", f"Each facility shows its type, health system, and network status, matching the facility file ({len(sample)} facilities)", not bad_facts, ", ".join(bad_facts[:3]))
        record("F2", f"Each facility shows the members living in its area, matching the membership file ({len(sample)} facilities)", not bad_members, ", ".join(bad_members[:3]))
        record("F3", f"Counts are labelled as member admissions ({len(sample)} facilities)", not bad_label, ", ".join(bad_label[:3]))
        with_hot = next(f for f in sample if f["high_alerts"])
        await page.click(f'#maptable [data-facility="{with_hot["id"]}"]')
        await axe("hospital summary")
        await page.locator("#detail .card").first.click()
        await page.wait_for_selector(".d-back")
        back_label = await page.inner_text(".d-back")
        await page.click(".d-back")
        await page.wait_for_timeout(200)
        name = await page.inner_text("#detail [data-subject]")
        record("H4", "A hotspot card opens that hotspot, with a link back to the facility", "Back to" in back_label and name == with_hot["name"])
        await page.click('[data-mode="map"]')
        await page.wait_for_timeout(200)
        record("L8", "The list still shows every hotspot after all of that", [r["id"] for r in await page.evaluate(LIST_JS)] == [a["id"] for a in alerts]
               and "Top hotspots" in list_html)

        # ---- Groups: by area (with a rate) and by health system ----
        area_wave = next((a for a in alerts if a.get("grouped_by") == "area"), None)
        if area_wave:
            await page.click(f'[data-alert="{area_wave["id"]}"]')
            await page.wait_for_function("!document.querySelector('[data-summary] .loading')")
            facts = await page.evaluate("Object.fromEntries([...document.querySelectorAll('#detail .facts > div')].map(d => [d.querySelector('dt').textContent.trim(), d.querySelector('dd').textContent.trim()]))")
            members = ds.membership[area_wave["area"]]["members"]
            want_rate = f"{area_wave['display']['observed'] / members * 1000:.1f} member admissions per 1,000 members"
            record("F4", "A hotspot covering a whole area shows a rate per 1,000 members, worked out from the membership file", facts.get("Rate for this diagnosis", "").startswith(want_rate), facts.get("Rate for this diagnosis", ""))
        single = next(a for a in alerts if a["kind"] == "pair")
        await page.click(f'[data-alert="{single["id"]}"]')
        await page.wait_for_function("!document.querySelector('[data-summary] .loading')")
        record("F5", "A hotspot at a single facility shows no rate per 1,000 members", "per 1,000" not in await page.inner_text("#panel-detected"))
        sys_wave = next((a for a in alerts if a.get("grouped_by") == "system"), None)
        if sys_wave:
            await page.click(f'[data-alert="{sys_wave["id"]}"]')
            await page.wait_for_function("!document.querySelector('[data-summary] .loading')")
            panel = await page.inner_text("#panel-detected")
            record("F6", "A system-wide hotspot names its health system and says the facilities are in different areas", sys_wave["system"] in panel and "different areas" in panel)
            await axe("system-wide hotspot")
        await page.click("[data-close]")
        plan = await page.inner_text("#panel-detected")
        known = ["Maimonides Medical Center", "Long Island Jewish Medical Center", "Lenox Hill Hospital", "Richmond University Medical Center", "Hackensack University Medical Center"]
        missing = [k for k in known if k not in set(fac_file["facility_name"])]
        record("F7", "Facilities carry their real hospital names, and the screen says the admissions and hotspots are made up for the demo",
               not missing and "real hospitals" in plan and "made up for the demo" in plan, ", ".join(missing))
        chrome = " ".join([await page.inner_text("#queue .p-title"), await page.inner_text(".map-title"), await page.inner_text("#detail .d-top"), await page.inner_text("#legend")])
        record("F8", "The screen says \"facility\", not \"hospital\", and says the counts are our members only", "hospital" not in chrome.lower() and "our members only" in plan)

        # ---- Map ----
        legend = await page.inner_text("#legend")
        water = await page.evaluate("getComputedStyle(document.querySelector('.map .water')).fill")
        r_, g_, b_ = [int(x) for x in re.findall(r"\d+", water)[:3]]
        record("M1", "Water on the map is blue, and the map key says so", "Blue: water" in legend and b_ > r_ and b_ > g_, water)
        dots = await page.evaluate("[...document.querySelectorAll('.fac.high .dot')].map(d => getComputedStyle(d).fill)")
        record("M2", "Top hotspots are red bubbles with their rank", bool(dots) and set(dots) == {"rgb(199, 46, 43)"}
               and await page.locator(".fac.high text.rank").count() == len(dots))

        # ---- Look ----
        stripe = await page.evaluate("getComputedStyle(document.querySelector('.topbar')).borderBottomColor")
        tab_bar = await page.evaluate("getComputedStyle(document.querySelector('[role=tab][aria-selected=true]')).borderBottomColor")
        record("B1", "Humana green is the accent: the stripe under the top bar and the selected tab", stripe == "rgb(120, 190, 32)" == tab_bar, f"{stripe} / {tab_bar}")
        reds = await page.evaluate("""() => { const out = new Set(); document.querySelectorAll('#queue *:not(.sr), #detail *:not(.sr), .topbar *:not(svg *)').forEach(e => {
            const s = getComputedStyle(e); for (const c of [s.color, s.backgroundColor]) if (c === 'rgb(199, 46, 43)') out.add(e.className.toString().split(' ').slice(0, 2).join('.')); }); return [...out]; }""")
        allowed = {"badge.rank", "fig-num.red", "card-num", "mbar", "over.end", "over", "recent-label", "pt"}
        record("B2", "Red is used only for hotspots: rank numbers, '+N', and hotspot bars", all(r in allowed for r in reds), ", ".join(reds))

        # ---- Wording that was removed ----
        everything = body + await page.inner_text("body")
        record("C3", "Nothing on screen mentions scaling up or a percentage of reports received",
               not re.search(r"scaled up|expected reports|% complete|still to come", everything, re.I))

        # ---- Narrow windows ----
        overflow = {}
        for w, h in ((1280, 720), (1024, 768), (390, 800)):
            p2 = await browser.new_page(viewport={"width": w, "height": h})
            await p2.goto(URL)
            await p2.wait_for_selector(".q-item")
            await p2.locator(".q-item").first.click()
            await p2.wait_for_timeout(500)
            overflow[w] = await p2.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            await p2.close()
        record("A2", "No sideways scrolling at 1280, 1024, or phone width", not any(overflow.values()), str(overflow))
        if axe_js:
            record("A1", "Automated accessibility scan (axe, WCAG A and AA) finds nothing in 9 states of the screen", not axe_found, json.dumps(axe_found) if axe_found else "")
        record("A3", "The page raises no errors in the browser", not errors, "; ".join(errors[:2]))
        await browser.close()

    passed = sum(r["passed"] for r in results)
    print(f"\n{passed} of {len(results)} dashboard checks pass.")
    if out_path:
        Path(out_path).write_text(json.dumps(results, indent=1))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None)))
