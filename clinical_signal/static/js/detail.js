// The right panel: "Summary". It is the only panel that changes with a click.
// A hotspot, and the whole-plan view, have three tabs, one for each part of the problem:
//   Detected            what was found (built)
//   What's driving it   possible causes from outside sources, for a person to confirm (built, see cause.js)
//   Who can act         the owner and recommendation for each confirmed cause (built, see action.js)
// A facility has no tabs: the tabs are about hotspots, so a facility is just its summary,
// and its hotspots are cards that open with the three tabs.
// The Detected tab summarises a hotspot or, with nothing selected, the whole plan. It answers first and keeps the supporting detail
// in drop-downs at the bottom. Nothing the left panel shows is repeated here.

import { esc, int, signed, money, dollars, rankBadge, withTip, barTable, codesKey, codeList } from "./format.js";
import { renderChart, chartNote } from "./chart.js";
import { causeIntro, causeLoading, causeView, reviewBox, saveName } from "./cause.js";
import { actionIntro, actionLoading, actionView } from "./action.js";

const SINGLE_FACILITY = new Set(["pair", "facility", "facility_wide"]);

const TABS = [
  { id: "detected", label: "Detected" },
  { id: "cause", label: "What’s driving it" },
  { id: "action", label: "Who can act" },
];

const tabList = `<div class="d-tabs" role="tablist" aria-label="The three parts of the work">${TABS.map((t, i) =>
  `<button type="button" role="tab" id="tab-${t.id}" data-tab="${t.id}" aria-controls="panel-${t.id}" aria-selected="${i === 0}" tabindex="${i === 0 ? 0 : -1}">${esc(t.label)}</button>`).join("")}</div>`;

// The fixed panel title, what is being summarised, and the tabs.
function frame({ about, title, sub, back = "", closable = true, tabs = true }, detected, cause = "", action = "") {
  const top = `<div class="d-top${tabs ? "" : " no-tabs"}">
      <div class="p-title"><h2 tabindex="-1">Summary</h2><p>${esc(about)}</p></div>
      <div class="d-subject"><div>${back}<h3 data-subject>${esc(title)}</h3>${sub ? `<p>${esc(sub)}</p>` : ""}</div>
        ${closable ? `<button type="button" class="d-close" data-close aria-label="Close and return to the plan summary">&times;</button>` : ""}</div>
      ${tabs ? tabList : ""}
    </div>`;
  if (!tabs) return `${top}<div class="d-body">${detected}</div>`;
  return `<div class="d-top">
      <div class="p-title"><h2 tabindex="-1">Summary</h2><p>${esc(about)}</p></div>
      <div class="d-subject"><div>${back}<h3 data-subject>${esc(title)}</h3>${sub ? `<p>${esc(sub)}</p>` : ""}</div>
        ${closable ? `<button type="button" class="d-close" data-close aria-label="Close and return to the plan summary">&times;</button>` : ""}</div>
      ${tabList}
    </div>
    <div class="d-body" role="tabpanel" id="panel-detected" aria-labelledby="tab-detected">${detected}</div>
    <div class="d-body" role="tabpanel" id="panel-cause" aria-labelledby="tab-cause" hidden>${cause}</div>
    <div class="d-body" role="tabpanel" id="panel-action" aria-labelledby="tab-action" hidden>${action}</div>`;
}

const block = (title, body, note = "") =>
  `<section class="d-block"><h4>${esc(title)}</h4>${note ? `<p class="d-sub">${note}</p>` : ""}${body}</section>`;

// A headline figure that can be opened up to show how it was worked out.
const figure = (id, value, label, tip, cls = "") => withTip(id,
  `<span class="fig-num ${cls}">${value}</span><span class="fig-label">${label}</span><span class="fig-how">How is this worked out?</span>`, tip, "fig");

// A closed drop-down at the bottom of the tab.
const drop = (name, label, body, attrs = "") =>
  `<details class="drop" data-drop="${name}" ${attrs}><summary><span class="caret" aria-hidden="true"></span>${esc(label)}</summary><div class="drop-body">${body}</div></details>`;

const codesDrop = (facilityIds, diagnoses) =>
  drop("codes", "Top diagnosis codes", `<div data-codes-body><p class="loading">Loading codes…</p></div>`,
    `data-codes="${esc(codesKey(facilityIds, diagnoses))}"`);

// ---------------------------------------------------------------- whole plan
function planView(o) {
  const m = o.meta, high = o.alerts.filter((a) => a.priority === "high");
  const hot = o.facilities.filter((f) => f.status === "high").length;
  const lead = o.alerts.length
    ? `<p class="d-text">Right now, <strong>${hot} of ${m.n_facilities} facilities</strong> are part of a top hotspot.</p>
       <p class="d-text">Everything here counts <b>our members only</b>: the admissions that facilities report to the plan. A facility's other patients are not in this data.</p>`
    : `<p class="d-text"><strong>No hotspots right now.</strong></p>`;
  return frame({ about: "Of the whole plan. Select a hotspot or a facility to summarise it instead.", title: "All facilities", sub: `Last ${m.window_days} days`, closable: false },
    `<section class="d-block">${lead}</section>
     ${block("What is a hotspot?", `<p class="d-text">A hotspot is a place where more of our members were admitted in the last ${m.window_days} days than we would normally expect. It can be one diagnosis at one facility, the same diagnosis at several nearby facilities or across one health system, or a whole facility.</p>
       <p class="d-text">A facility is an outside inpatient provider the plan contracts with, such as an acute care hospital or an inpatient psychiatric facility. The plan does not run it.</p>
       <p class="d-text">A hotspot says <b>where</b> something unusual is happening. It does not say why.</p>`)}
     ${block("How we find one", `<p class="d-text">We count the member admissions reported for every facility and every diagnosis, and compare them with the past in four ways:</p>
       <ul class="plain"><li>the same four weeks in past years</li><li>the four weeks before</li><li>the latest week against the three before it</li><li>whether the count is climbing week after week</li></ul>
       <p class="d-text">If any of the four shows a clear, large enough increase, it becomes a hotspot. The ${high.length || m.top_n} largest are listed as top hotspots. This step uses fixed rules, not AI.</p>`)}
     ${block("About this data", `<p class="d-text">This is a prototype. The facilities are <b>real hospitals</b> in the New York area, shown with their real names and locations. Everything else is <b>made up for the demo</b>: the member admissions, the hotspots, the costs, the network status and the member counts. Nothing here describes what really happened at any hospital.</p>`)}`,
    causeIntro(m, "Select a hotspot to see what may be driving it."),
    actionIntro(m, "Select a hotspot to see who can act on it."));
}

// ------------------------------------------------------------------ hospital
// How the number of members living in an area has moved in a year, in words.
function memberChange(now, before) {
  if (!now || !before) return "";
  const pct = Math.round((now / before - 1) * 100);
  return pct > 0 ? `up ${pct}% on last year` : pct < 0 ? `down ${Math.abs(pct)}% on last year` : "unchanged on last year";
}

// The plain facts about a facility: what it is, whose it is, and who lives nearby.
// These are labels only. None of them changes what is detected.
function facilityFacts(f) {
  const members = f.area_members
    ? `<div><dt>Members living in ${esc(f.area)}</dt><dd>${int(f.area_members)}, ${memberChange(f.area_members, f.area_members_year_ago)}</dd></div>` : "";
  return `<dl class="facts">
    <div><dt>Type of facility</dt><dd>${esc(f.type)}</dd></div>
    <div><dt>Health system</dt><dd>${esc(f.system)}</dd></div>
    <div><dt>Network status</dt><dd>${esc(f.network)}</dd></div>
    ${members}</dl>`;
}

function hospitalCard(a, f) {
  // Inside a group of facilities, this facility's own share is what matters here.
  const own = a.kind === "wave" ? a.members.find((m) => m.facility_id === f.id) : null;
  const excess = (own || a).display.excess;
  const cost = own ? Math.max(excess, 0) * a.avg_cost : a.excess_spend;
  const part = a.kind === "wave" ? `<span class="card-sub">Part of a group: ${esc(a.subtitle)}</span>` : "";
  return `<li><button type="button" class="card" data-alert="${esc(a.id)}" data-from="${esc(f.id)}">
    ${rankBadge(a)}<span class="card-main"><span class="card-title">${esc(a.title)}</span>${part}</span>
    <span class="card-figs"><span class="card-num">${signed(excess)}<span class="sr"> member admissions above expected</span></span><span class="card-cost">${money(cost)} est.</span></span></button></li>`;
}

function hospitalView(f, o) {
  const byId = new Map(o.alerts.map((a) => [a.id, a]));
  const alerts = [...f.high_alerts, ...f.low_alerts].map((id) => byId.get(id));
  const d = f.display;
  const totals = `<div class="figs">
      ${figure("fig-hosp-n", int(d.observed), "member admissions here in the last 28 days",
        `Every admission of one of our members that this facility has reported, with an admission date in the last 28 days, all diagnoses together. The facility's other patients are not counted.`, "plain")}
      ${d.expected == null ? "" : figure("fig-hosp-e", int(d.expected), "is usual for these four weeks",
        `The average for the same four weeks in past years at this facility, adjusted for how much the plan has grown.`, "plain")}
    </div>`;
  const list = alerts.length
    ? `<ul class="cards">${alerts.map((a) => hospitalCard(a, f)).join("")}</ul><p class="d-hint">Select one to see what was detected, what may be driving it, and who can act.</p>`
    : `<p class="d-quiet">No hotspots at this facility right now.</p>`;
  return frame({ about: "Of the facility you selected on the map.", title: f.name, sub: `${f.type} in ${f.area}`, tabs: false },
    `<section class="d-block">${totals}</section>
     ${block("About this facility", facilityFacts(f))}
     ${block(alerts.length ? `Hotspots at this facility (${alerts.length})` : "Hotspots at this facility", list)}
     <div class="drops">${codesDrop([f.id], null)}</div>`);
}

// ------------------------------------------------------------------- hotspot
// What each of the four checks looks for, in plain words, and what it found.
const CHECKS = {
  seasonal: {
    yes: "Higher than the same four weeks in past years", no: "Not unusually high for this time of year",
    none: "No past years to compare with",
    how: (c) => `${int(c.display.observed)} admissions in the last 28 days. The same four weeks in past years averaged ${int(c.display.expected)}.`,
  },
  prior_period: {
    yes: "Higher than the four weeks before", no: "Not unusually higher than the four weeks before",
    how: (c) => `${int(c.display.observed)} admissions in the last 28 days. There were ${int(c.display.expected)} in the 28 days before that.`,
  },
  latest_week: {
    yes: "A jump in the latest week", no: "No unusual jump in the latest week",
    how: (c) => `${int(c.display.observed)} admissions in the latest week. The three weeks before averaged ${int(c.display.expected)} a week.`,
  },
  trend: {
    yes: "Climbing week after week", no: "Not climbing week after week",
    how: (c, a) => `Admissions in each of the last four weeks, oldest first: ${a.weekly4.map((v) => int(v)).join(", ")}.`,
  },
};

function checklist(a, meta) {
  const need = a.kind === "pair" ? meta.min_excess.pair : meta.min_excess.group;
  const rows = a.comparisons.map((c, i) => {
    const t = CHECKS[c.key], none = c.expected == null;
    const text = none ? t.none : c.fired ? t.yes : t.no;
    const seasonal = c.key === "prior_period" && !c.fired && (c.season_factor ?? 1) >= 1.1 && c.display.excess >= need;
    const verdict = none ? "" : seasonal
      ? ` Past years show a rise of about ${Math.round((c.season_factor - 1) * 100)}% at this time of year, so this much is normal for the season and this check did not count it.`
      : c.fired
      ? ` That is at least ${need} more than expected and well outside the normal ups and downs, so this check found an increase.`
      : ` That is within the normal ups and downs, or fewer than ${need} more than expected, so this check did not find an increase.`;
    return `<li>${withTip(`check-tip-${i}`,
      `<span class="mark" aria-hidden="true">${c.fired ? "&#10003;" : "&ndash;"}</span><span class="sr">${c.fired ? "Found: " : "Not found: "}</span><span class="check-text">${esc(text)}</span>`,
      `${none ? "There is not enough history for this comparison." : esc(t.how(c, a))}${verdict}`, `check${c.fired ? " is-on" : ""}`)}</li>`;
  }).join("");
  return `<ul class="checks">${rows}</ul><p class="d-hint">Hover over a line, or tab to it, to see the numbers behind it.</p>`;
}

function membersDrop(a) {
  if (!a.members.length) return "";
  const hospitals = a.members.map((m) => ({ name: m.short_name, title: m.facility, display: m.display, facilityId: m.facility_id }));
  const groups = a.members.map((m) => ({ name: m.diagnosis, display: m.display }));
  const foot = `<p class="note">Each row is its own count against its own expected count. The solid part of a bar is the amount above expected.`;
  if (a.kind === "wave") return drop("members", `The ${a.members.length} facilities in this hotspot`,
    barTable(hospitals, { nameHeader: "Facility", caption: "Facilities in this hotspot", flagged: true }) + `${foot} Select a facility to see its summary.</p>`);
  if (a.kind === "plan_wide") return drop("members", "Facilities with the largest increases",
    barTable(hospitals, { nameHeader: "Facility", caption: "Facilities with the largest increases" }) + `${foot} None of these would be a hotspot alone.</p>`);
  if (a.kind === "facility") return drop("members", `The ${a.members.length} diagnosis groups that are up`,
    barTable(groups, { nameHeader: "Diagnosis group", caption: "Diagnosis groups that are up at this facility", flagged: true }) + `${foot}</p>`);
  return drop("members", "Diagnosis groups with the largest increases",
    barTable(groups, { nameHeader: "Diagnosis group", caption: "Diagnosis groups with the largest increases" }) + `${foot} None of these would be a hotspot alone.</p>`);
}

function hotspotCodes(a) {
  if (a.diagnosis) return codesDrop(a.kind === "plan_wide" ? null : a.facility_ids, [a.diagnosis]);
  const flaggedOnly = a.kind === "facility" && a.scope !== "all admissions";
  return codesDrop(a.facility_ids, flaggedOnly ? a.members.map((m) => m.diagnosis) : null);
}

function hotspotView(a, o, from) {
  const d = a.display;
  const facility = SINGLE_FACILITY.has(a.kind) ? o.facilities.find((f) => f.id === a.facility_ids[0]) : null;
  const where = facility ? facility.short_name : a.subtitle;
  const fromFacility = from ? o.facilities.find((f) => f.id === from) : null;
  const back = fromFacility ? `<button type="button" class="d-back" data-facility="${esc(fromFacility.id)}">Back to ${esc(fromFacility.short_name)}</button>` : "";
  const what = a.diagnosis ? `member admissions for ${a.title}` : "member admissions";
  // Who and where: one facility's facts, or, for a group, what links its facilities.
  let about = "";
  if (facility) {
    about = block("About this facility", facilityFacts(facility));
  } else if (a.grouped_by === "system") {
    const areas = [...new Set(a.facility_ids.map((id) => o.facilities.find((f) => f.id === id).area))];
    about = block("About these facilities", `<dl class="facts">
      <div><dt>Health system</dt><dd>${esc(a.system)}</dd></div>
      <div><dt>Where they are</dt><dd>${esc(areas.join(", "))}</dd></div></dl>
      <p class="d-hint">These facilities are in different areas. What they share is the health system the plan contracts with.</p>`);
  } else if (a.grouped_by === "area") {
    const any = o.facilities.find((f) => f.id === a.facility_ids[0]);
    const per = (n) => (n / any.area_members * 1000).toFixed(1);
    about = block("About this area", `<dl class="facts">
      <div><dt>Members living in ${esc(a.area)}</dt><dd>${int(any.area_members)}, ${memberChange(any.area_members, any.area_members_year_ago)}</dd></div>
      <div><dt>Rate for this diagnosis</dt><dd>${per(d.observed)} member admissions per 1,000 members in the ${esc(a.period)}; ${per(d.expected)} is usual</dd></div></dl>
      <p class="d-hint">A rate is shown here because this hotspot covers a whole area. It is not shown for a single facility, because several facilities share the same members.</p>`);
  }
  const figs = `<div class="figs">
      ${figure("fig-excess", signed(d.excess), "member admissions above expected",
        `${int(d.observed)} member admissions were reported in the ${esc(a.period)}. We expected ${int(d.expected)}, based on ${esc(a.baseline)}. ${int(d.observed)} &minus; ${int(d.expected)} = ${int(d.excess)} more than expected.`, "red")}
      ${figure("fig-cost", money(a.excess_spend), "estimated extra cost",
        `${int(d.excess)} extra member admissions &times; ${dollars(a.avg_cost)} each = about ${money(a.excess_spend)}. ${dollars(a.avg_cost)} is the average amount paid for this kind of admission here over the past year. It is an estimate, not a bill.`, "plain")}
    </div>`;
  return frame({ about: "Of the hotspot you selected.", title: a.title, sub: a.subtitle, back },
    `<section class="d-block">${figs}</section>
     ${block("What was detected", `<p class="d-text" data-summary><span class="loading">Writing summary…</span></p><p class="d-source" data-source></p>`)}
     ${about}
     ${block("How we detected it", checklist(a, o.meta),
       `We compare the latest member admissions with the past in four ways. A check mark means that comparison found an unusual increase. <b>${a.n_fired} of ${a.comparisons.length}</b> did here.`)}
     <div class="drops">
       ${membersDrop(a)}
       ${hotspotCodes(a)}
       ${drop("chart", "12-month history chart", `<h5 class="chart-title">Weekly ${esc(what)} at ${esc(where)}, past 12 months</h5>
         <div class="chart" data-chart><p class="loading">Loading chart…</p></div>${chartNote}<div data-table></div>`)}
     </div>`,
    causeLoading(), actionLoading());
}

function weeklyTable(chart) {
  const rows = chart.slice(-12).reverse().map((d) => `<tr><th scope="row">${esc(new Date(`${d.week_start}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" }))}</th><td>${int(d.value)}</td>
    <td>${d.expected == null ? "n/a" : `${int(d.low)} to ${int(d.high)}`}</td></tr>`).join("");
  return `<details class="table"><summary>Show the last 12 weeks as a table</summary>
    <table><thead><tr><th scope="col">Week of</th><th scope="col">Admissions</th><th scope="col">Normal range</th></tr></thead><tbody>${rows}</tbody></table></details>`;
}

export function createDetail(el, handlers) {
  let chartRows = null, codes = new Map();

  function selectTab(id, focus = false) {
    el.querySelectorAll("[role=tab]").forEach((t) => {
      const on = t.dataset.tab === id;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
    });
    el.querySelectorAll("[role=tabpanel]").forEach((p) => { p.hidden = p.id !== `panel-${id}`; });
    el.scrollTop = 0;
  }

  // The chart is drawn when its drop-down is opened, so it is sized to the space it really has.
  function drawChart() {
    const box = el.querySelector("[data-chart]");
    if (!box || !chartRows || !box.closest("details").open) return;
    renderChart(box, chartRows);
    el.querySelector("[data-table]").innerHTML = weeklyTable(chartRows);
  }

  function fillCodes() {
    const d = el.querySelector("details[data-codes]");
    if (!d || !d.open) return;
    const key = d.dataset.codes;
    d.querySelector("[data-codes-body]").innerHTML = codeList(codes.get(key) ?? null);
    if (!codes.has(key)) handlers.onNeedCodes(key);
  }

  // A person's decision on a possible cause. Pressing the chosen button again clears it.
  function sendReview(box, decision) {
    const name = el.querySelector("[data-reviewer]")?.value.trim() || "";
    handlers.onReview(box.dataset.topic, decision, box.querySelector("[data-note]").value, name);
  }
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-review]");
    if (b) sendReview(b.closest(".rv"), b.getAttribute("aria-pressed") === "true" ? null : b.dataset.review);
  });
  // Part three: a person's step on one recommendation. Each step is saved, then the tab is redrawn.
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const box = b.closest(".ad"), topic = box.dataset.topic, act = b.dataset.act;
    const val = (sel) => box.querySelector(sel)?.value ?? "";
    const reviewer = el.querySelector("[data-act-reviewer]")?.value.trim() || "";
    if (act === "accepted" || act === "declined") handlers.onAction(topic, "decision", { decision: act, text: val("[data-act-text]"), note: val("[data-act-note]"), reviewer });
    else if (act === "undo") handlers.onAction(topic, "decision", { decision: null });
    else if (act === "handoff") handlers.onAction(topic, "handoff", { subject: val("[data-ho-subject]"), body: val("[data-ho-body]") });
    else if (act === "unhandoff") handlers.onAction(topic, "handoff", { undo: true });
    else if (act === "agreed" || act === "owner-declined") {
      const pressed = b.getAttribute("aria-pressed") === "true";   // pressing the chosen answer again clears it
      handlers.onAction(topic, "answer", { answer: pressed ? null : act === "agreed" ? "agreed" : "declined", note: val("[data-ans-note]") });
    } else if (act === "copy") handlers.onCopy(`Subject: ${val("[data-ho-subject]")}\n\n${val("[data-ho-body]")}`);
  });
  el.addEventListener("change", (e) => {
    if (e.target.matches("[data-reviewer]")) saveName(e.target.value.trim());
    if (e.target.matches("[data-act-reviewer]")) saveName(e.target.value.trim());
    // A note edited after deciding is saved with the decision already made.
    const box = e.target.matches("[data-note]") ? e.target.closest(".rv") : null;
    const chosen = box?.querySelector('[data-review][aria-pressed="true"]');
    if (chosen) sendReview(box, chosen.dataset.review);
  });

  el.addEventListener("click", (e) => {
    const t = e.target.closest("[data-close],[data-tab],[data-alert],[data-facility]");
    if (!t) return;
    if ("close" in t.dataset) handlers.onClose();
    else if (t.dataset.tab) selectTab(t.dataset.tab);
    else if (t.dataset.alert) handlers.onSelectAlert(t.dataset.alert, t.dataset.from || null);
    else if (t.dataset.facility) handlers.onSelectFacility(t.dataset.facility);
  });
  // Left and right arrows move between tabs, as tabs do everywhere else.
  el.addEventListener("keydown", (e) => {
    const tab = e.target.closest?.("[data-tab]");
    if (!tab) return;
    const i = TABS.findIndex((t) => t.id === tab.dataset.tab);
    const next = e.key === "ArrowRight" ? (i + 1) % TABS.length : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
      : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1;
    if (next < 0) return;
    e.preventDefault();
    selectTab(TABS[next].id, true);
  });
  el.addEventListener("toggle", (e) => {
    if (!e.target.matches("details.drop") || !e.target.open) return;
    if (e.target.dataset.drop === "chart") drawChart();
    if (e.target.dataset.drop === "codes") fillCodes();
  }, true);

  const show = (html) => { chartRows = null; el.innerHTML = html; el.scrollTop = 0; };

  return {
    showPlan(overview) {
      show(overview ? planView(overview) : frame({ about: "Of the whole plan.", title: "All facilities", sub: "Looking for hotspots…", closable: false }, ""));
    },
    showFacility(facility, overview) { show(hospitalView(facility, overview)); },
    showAlert(a, overview, from) { show(hotspotView(a, overview, from)); },
    focus() { el.querySelector(".p-title h2")?.focus({ preventScroll: true }); },

    setChart(chart) { chartRows = chart; drawChart(); },
    // Part two: the possible causes for the selected hotspot.
    setCauses(data) {
      const box = el.querySelector("[data-causes]");
      if (box) box.innerHTML = causeView(data);
    },
    // Part three: who can act on the selected hotspot. `focusTopic` puts keyboard focus back in the card that was just changed.
    setActions(data, focusTopic = null) {
      const box = el.querySelector("[data-actions]");
      if (!box) return;
      box.innerHTML = actionView(data);
      if (focusTopic) box.querySelector(`.ad[data-topic="${CSS.escape(focusTopic)}"] button`)?.focus();
    },
    // One cause after a decision was saved: only its decision box is redrawn, so open evidence stays open.
    setReview(cause) {
      const find = () => el.querySelector(`.rv[data-topic="${CSS.escape(cause.topic)}"]`);
      const box = find();
      if (!box) return;
      box.outerHTML = reviewBox(cause, box.querySelector("[data-note]").id.replace("rv-note-", ""));
      find().querySelector(cause.review ? `[data-review="${cause.review.decision}"]` : "[data-review]")?.focus();
    },
    setSummary(s) {
      const box = el.querySelector("[data-summary]");
      if (!box) return;
      box.textContent = s.text || "";
      el.querySelector("[data-source]").textContent = s.note || "";
    },
    setCodes(key, data) { if (!data.error) codes.set(key, data); const d = el.querySelector("details[data-codes]"); if (d && d.dataset.codes === key && d.open) d.querySelector("[data-codes-body]").innerHTML = codeList(data); },
    clearCodes() { codes = new Map(); },
    setError(message) {
      const box = el.querySelector("[data-chart]");
      if (box) box.innerHTML = `<p class="loading">${esc(message)}</p>`;
    },
  };
}
