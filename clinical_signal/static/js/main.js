// Wires the three panels together. Each has one job:
//   left    "Top hotspots": the list. It never changes shape and is never filtered.
//   middle  "Map": every hospital. Clicking one selects it.
//   right   "Summary": explains whatever is selected, under three fixed tabs.
// All shared state lives here; each part only renders what it is given.

import { fetchOverview, fetchAlert, fetchSummary, fetchCodes, fetchRegion, fetchCauses, postReview, fetchActions, postAction } from "./api.js";
import { createMap } from "./map.js";
import { createQueue } from "./queue.js";
import { createDetail } from "./detail.js";
import { createFacilityTable } from "./facilitytable.js";
import { longDate, shortDate, int, signed } from "./format.js";

const state = {
  overview: null,
  selection: null,   // { type: "alert" | "facility", id, from? }: what the Summary panel explains
  hoverAlertId: null,
  showMore: false,   // whether the extra hotspots under the top list are open
};

const alertById = (id) => state.overview?.alerts.find((a) => a.id === id);
const isSelected = (type, id) => state.selection?.type === type && state.selection.id === id;
const mapCol = document.querySelector(".mapcol");
const statusEl = document.getElementById("status");

// Tell screen-reader users what just changed; sighted users see it happen.
const announce = (text) => { statusEl.textContent = ""; requestAnimationFrame(() => { statusEl.textContent = text; }); };

const queue = createQueue(document.getElementById("queue"), {
  onSelectAlert: (id) => selectAlert(id, null, "list"),
  onHoverAlert: (id) => { state.hoverAlertId = id; syncMap(); },
  onToggleMore: () => { state.showMore = !state.showMore; queue.render(state); queue.focus("[data-more]"); },
});

const map = createMap(document.getElementById("map"), document.getElementById("legend"), {
  onFacilityClick: (id) => (isSelected("facility", id) ? clearSelection() : selectFacility(id)),
  onWaveClick: (id) => (isSelected("alert", id) ? clearSelection() : selectAlert(id, null, "map")),
  onBackgroundClick: () => { if (state.selection) clearSelection(); },
  onFacilityHover: (id) => queue.setLinked(id),
  onWaveHover: (id) => { state.hoverAlertId = id; syncMap(); },
});

const table = createFacilityTable(document.getElementById("maptable"), { onSelectFacility: (id) => selectFacility(id) });

const detail = createDetail(document.getElementById("detail"), {
  onClose: clearSelection,
  onSelectAlert: (id, from) => selectAlert(id, from, "summary"),
  onSelectFacility: (id) => selectFacility(id, "summary"),
  // A person confirms, rejects, or is not sure about a possible cause (part two).
  onReview: (topic, decision, note, reviewer) => {
    const sel = state.selection;
    if (sel?.type !== "alert") return;
    postReview(sel.id, topic, { decision, note, reviewer })
      .then((cause) => {
        if (state.selection !== sel) return;
        detail.setReview(cause);
        const said = { confirmed: "confirmed", rejected: "rejected", unsure: "marked not sure" }[cause.review?.decision];
        announce(said ? `${cause.label}: ${said}.` : `${cause.label}: decision cleared.`);
        // Only a confirmed cause gets a recommendation, so the third tab is worked out again.
        fetchActions(sel.id).then((a) => { if (state.selection === sel) detail.setActions(a); }).catch(() => {});
      })
      .catch((err) => announce(`The decision could not be saved: ${err.message}`));
  },
  // A person accepts or declines a recommendation, marks it handed off, or records the owner's answer (part three).
  onAction: (topic, step, body) => {
    const sel = state.selection;
    if (sel?.type !== "alert") return;
    postAction(sel.id, topic, step, body)
      .then((data) => {
        if (state.selection !== sel) return;
        detail.setActions(data, topic);
        const stage = data.recommendations.find((r) => r.topic === topic)?.stage;
        announce({ to_decide: "Decision cleared.", accepted: "Recommendation accepted. The hand-off message is ready to copy.", declined: "Recommendation declined.",
          handed_off: "Marked as handed off.", agreed: "Recorded: the owner agreed.", owner_declined: "Recorded: the owner said this is not the right action." }[stage] || "Saved.");
      })
      .catch((err) => announce(`That could not be saved: ${err.message}`));
  },
  onCopy: (text) => {
    (navigator.clipboard?.writeText(text) ?? Promise.reject(new Error("no clipboard")))
      .then(() => announce("Message copied."))
      .catch(() => announce("The message could not be copied. Select the text and copy it by hand."));
  },
  onNeedCodes: (key) => {
    const [facilityIds, diagnoses] = JSON.parse(key);
    fetchCodes(facilityIds, diagnoses).catch(() => ({ error: true })).then((data) => {
      detail.setCodes(key, data);
      if (!data.error) announce(`${data.codes.length} diagnosis ${data.codes.length === 1 ? "code" : "codes"} shown.`);
    });
  },
});

// What the map should emphasise right now: whatever is hovered, else the selection.
function syncMap() {
  const sel = state.selection;
  const focus = alertById(state.hoverAlertId) || (sel?.type === "alert" ? alertById(sel.id) : null);
  let facilityIds = null, waveId = null;
  if (focus) {
    facilityIds = focus.facility_ids;
    waveId = focus.kind === "wave" ? focus.id : null;
  } else if (sel?.type === "facility") {
    facilityIds = [sel.id];
  }
  map.setHighlight({ facilityIds, waveId, selected: sel?.type === "facility" ? sel.id : null });
  table.setSelected(sel?.type === "facility" ? sel.id : null);
}

// `via` is where the choice was made. A choice in the list leaves keyboard focus on
// its row; a choice anywhere else moves focus to the Summary panel, which is what changed.
function selectAlert(id, from = null, via = "list") {
  const a = alertById(id);
  if (!a) return;
  state.selection = { type: "alert", id, from };
  state.hoverAlertId = null;
  if (a.priority === "low") state.showMore = true;   // make sure its row can be seen in the list
  queue.render(state);
  if (via === "list") queue.focus(`[data-alert="${CSS.escape(id)}"]`); else queue.reveal();
  detail.showAlert(a, state.overview, from);
  if (via !== "list") detail.focus();
  syncMap();
  announce(`Summary now shows the hotspot ${a.title}, ${a.subtitle}. ${signed(a.display.excess)} member admissions above expected.`);
  const sel = state.selection;
  const current = () => state.selection === sel;
  fetchAlert(id)
    .then((d) => { if (current()) detail.setChart(d.chart); })
    .catch((err) => { if (current()) detail.setError(`The chart could not be loaded: ${err.message}`); });
  fetchCauses(id)
    .then((c) => { if (current()) detail.setCauses(c); })
    .catch((err) => { if (current()) detail.setCauses({ error: err.message }); });
  fetchActions(id)
    .then((c) => { if (current()) detail.setActions(c); })
    .catch((err) => { if (current()) detail.setActions({ error: err.message }); });
  fetchSummary(id)
    .then((s) => { if (current()) detail.setSummary(s); })
    .catch(() => { if (current()) detail.setSummary({ text: "The summary could not be loaded.", note: "" }); });
}

function selectFacility(id, via = "map") {
  const facility = state.overview.facilities.find((f) => f.id === id);
  if (!facility) return;
  state.selection = { type: "facility", id };
  state.hoverAlertId = null;
  queue.render(state);                 // only clears the highlighted row; the list itself stays as it is
  detail.showFacility(facility, state.overview);
  if (via === "summary") detail.focus();
  syncMap();
  const n = facility.high_alerts.length + facility.low_alerts.length;
  announce(`Summary now shows ${facility.name}. ${n ? `${n} ${n === 1 ? "hotspot" : "hotspots"} here.` : "No hotspots here."}`);
}

function clearSelection() {
  const was = state.selection;
  state.selection = null;
  state.hoverAlertId = null;
  queue.render(state);
  detail.showPlan(state.overview);
  syncMap();
  if (was) announce("Summary now shows the whole plan.");
}

function renderTopBar() {
  const m = state.overview.meta;
  document.getElementById("asof").innerHTML =
    `Data through <strong>${longDate(m.as_of)}</strong>. ${int(m.admissions_reported)} member admissions reported in the last ${m.window_days} days (${shortDate(m.window_start)} to ${shortDate(m.as_of)}).`;
}

async function load() {
  queue.render(state);
  detail.showPlan(null);
  try {
    state.overview = await fetchOverview();
  } catch (err) {
    document.getElementById("queue").innerHTML = `<div class="q-empty" role="alert"><strong>The hotspots could not be loaded.</strong>${err.message}. Check that the app is still running, then reload the page.</div>`;
    return;
  }
  renderTopBar();
  map.setData(state.overview);
  table.render(state.overview);
  queue.render(state);
  detail.showPlan(state.overview);
}

// Map or table: two views of the same hospitals.
document.querySelector(".mode").addEventListener("click", (e) => {
  const b = e.target.closest("[data-mode]");
  if (!b) return;
  mapCol.dataset.mode = b.dataset.mode;
  document.querySelectorAll(".mode button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
});
document.querySelector(".segmented.view").addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]");
  if (!b) return;
  document.querySelectorAll(".segmented.view button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  map.setView(b.dataset.view);
});
document.querySelector(".zoom").addEventListener("click", (e) => {
  const b = e.target.closest("[data-zoom]");
  if (b) map.zoomBy(b.dataset.zoom === "in" ? 1.6 : 1 / 1.6);
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (map.hideTip()) return;            // first Escape dismisses the map's tooltip
  // ...or an open explanation box, whether it was opened by pointer or keyboard.
  const host = document.querySelector(".has-tip:hover:not(.tip-off), .has-tip:focus-within:not(.tip-off)");
  if (host) {
    host.classList.add("tip-off");
    const restore = () => { host.classList.remove("tip-off"); host.removeEventListener("mouseleave", restore); host.removeEventListener("focusout", restore); };
    host.addEventListener("mouseleave", restore);
    host.addEventListener("focusout", restore);
    return;
  }
  if (state.selection) clearSelection();
});

fetchRegion().then(map.setGeo);
load();
