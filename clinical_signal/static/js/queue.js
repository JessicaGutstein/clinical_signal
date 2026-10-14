// The left panel: "Top hotspots". It is only ever the list of hotspots.
// Clicking a row selects it and the Summary panel on the right explains it; the
// list itself never changes shape, and it is never filtered by a click on the map.

import { esc, int, rankBadge } from "./format.js";

const SINGLE_FACILITY = new Set(["pair", "facility", "facility_wide"]);

// Where the hotspot is: the facility's short name, or "6 hospitals in Queens".
function place(a, s) {
  if (!SINGLE_FACILITY.has(a.kind)) return a.subtitle;
  return s.overview.facilities.find((f) => f.id === a.facility_ids[0])?.short_name || a.subtitle;
}

// One row: rank, what, where, and the count against what was expected.
// How far above expected it is, and what that costs, are on the right.
function row(a, s) {
  const d = a.display, selected = s.selection?.type === "alert" && s.selection.id === a.id;
  const period = a.period === "last 28 days" ? "" : `<span class="q-period">${esc(a.period)}</span>`;
  return `<li><button type="button" class="q-item${a.priority === "low" ? " is-low" : ""}${selected ? " is-selected" : ""}"
      data-alert="${esc(a.id)}" data-facilities="${esc(a.facility_ids.join(" "))}"${selected ? ' aria-current="true"' : ""}>
    ${rankBadge(a)}
    <span class="q-main"><span class="q-title">${esc(a.title)}</span><span class="q-sub">${esc(place(a, s))}</span></span>
    <span class="q-figure"><span class="q-count">${int(d.observed)}<span class="sr"> member admissions reported,</span></span>
      <span class="q-vs">vs ${int(d.expected)} expected</span>${period}</span>
  </button></li>`;
}

function view(s) {
  const { alerts, meta } = s.overview;
  const high = alerts.filter((a) => a.priority === "high");
  const low = alerts.filter((a) => a.priority === "low");
  const head = `<div class="p-title"><h2 tabindex="-1" data-focus>Top hotspots</h2>
    <p>Where member admissions are unusually high in the last ${meta.window_days} days. Select one to see its summary.</p></div>`;
  if (!alerts.length) {
    return `${head}<div class="q-empty"><strong>No hotspots right now.</strong>
      Nothing is unusually high in the last ${meta.window_days} days. Select any facility on the map to see its summary.</div>`;
  }
  const more = low.length
    ? `<div class="q-more"><button type="button" data-more aria-expanded="${s.showMore}">
         <span class="caret" aria-hidden="true"></span><span>${s.showMore ? "Hide" : "Show"} ${low.length} more ${low.length === 1 ? "hotspot" : "hotspots"}</span></button>
       ${s.showMore ? `<p class="q-more-note">Smaller or less certain than the top ${high.length}.</p><ul class="q-list">${low.map((a) => row(a, s)).join("")}</ul>` : ""}</div>`
    : "";
  return `${head}<ul class="q-list">${high.map((a) => row(a, s)).join("")}</ul>${more}`;
}

export function createQueue(el, handlers) {
  el.addEventListener("click", (e) => {
    const t = e.target.closest("[data-alert],[data-more]");
    if (!t) return;
    if (t.dataset.alert) handlers.onSelectAlert(t.dataset.alert);
    else handlers.onToggleMore();
  });
  // Hovering (or tabbing to) a row lights up its bubbles on the map.
  const enter = (e) => { const t = e.target.closest("[data-alert]"); if (t) handlers.onHoverAlert(t.dataset.alert); };
  const leave = (e) => { if (e.target.closest("[data-alert]")) handlers.onHoverAlert(null); };
  el.addEventListener("mouseover", enter);
  el.addEventListener("mouseout", leave);
  el.addEventListener("focusin", enter);
  el.addEventListener("focusout", leave);

  return {
    // Redraws the list in place, keeping the reader's scroll position.
    render(state) {
      if (!state.overview) { el.innerHTML = `<div class="p-title"><h2>Top hotspots</h2><p class="loading">Looking for hotspots…</p></div>`; return; }
      const top = el.scrollTop;
      el.innerHTML = view(state);
      el.scrollTop = top;
    },
    focus(selector) { el.querySelector(selector)?.focus({ preventScroll: true }); },
    // Bring the selected row into view when it was chosen somewhere else (the map, a card).
    reveal() { el.querySelector(".q-item.is-selected")?.scrollIntoView({ block: "nearest" }); },
    // Hovering a bubble marks the rows that involve that facility.
    setLinked(facilityId) {
      el.querySelectorAll("[data-facilities]").forEach((item) => {
        item.classList.toggle("is-linked", !!facilityId && item.dataset.facilities.split(" ").includes(facilityId));
      });
    },
  };
}
