// A table of every facility: the text alternative to the bubble map. Everything the
// map shows (who is a hotspot, how far above expected) is here in words and numbers,
// and every row can be selected from the keyboard.

import { esc, int, signed } from "./format.js";

export function createFacilityTable(el, handlers) {
  el.addEventListener("click", (e) => {
    const b = e.target.closest("[data-facility]");
    if (b) handlers.onSelectFacility(b.dataset.facility);
  });

  let selectedId = null;

  return {
    render(overview) {
      const byId = new Map(overview.alerts.map((a) => [a.id, a]));
      const tier = { high: 0, low: 1, none: 2 };
      const rows = overview.facilities.map((f) => {
        const ids = f.status === "high" ? f.high_alerts : f.low_alerts;
        const rank = ids.length ? Math.min(...ids.map((id) => byId.get(id).rank)) : null;
        return { f, rank };
      }).sort((a, b) => tier[a.f.status] - tier[b.f.status] || (a.rank ?? 0) - (b.rank ?? 0) ||
        (b.f.display.excess ?? 0) - (a.f.display.excess ?? 0));
      const status = ({ f, rank }) => f.status === "high" ? `<span class="badge high">Top hotspot, rank ${rank}</span>`
        : f.status === "low" ? `<span class="badge low">Hotspot, rank ${rank}</span>` : `<span class="ft-none">No hotspot</span>`;
      el.innerHTML = `<table class="ft">
        <caption>All ${overview.facilities.length} facilities, last ${overview.meta.window_days} days, hotspots first. The counts are our members admitted to each facility, all diagnoses together, so a hotspot in one diagnosis can sit in a facility that is at or below expected overall.</caption>
        <thead><tr><th scope="col">Facility, health system and area</th><th scope="col">Status</th>
          <th scope="col" class="num">Member admissions</th><th scope="col" class="num">Expected</th><th scope="col" class="num">Difference</th></tr></thead>
        <tbody>${rows.map((r) => `<tr data-row="${esc(r.f.id)}"${r.f.id === selectedId ? ` class="is-selected"` : ""}>
          <th scope="row"><button type="button" class="bt-link" data-facility="${esc(r.f.id)}"${r.f.id === selectedId ? ` aria-current="true"` : ""}>${esc(r.f.name)}</button><span class="ft-area">${esc(r.f.system)} · ${esc(r.f.area)}</span></th>
          <td>${status(r)}</td>
          <td class="num">${int(r.f.display.observed)}</td><td class="num">${r.f.display.expected == null ? "n/a" : int(r.f.display.expected)}</td>
          <td class="num">${r.f.display.excess == null ? "" : signed(r.f.display.excess)}</td></tr>`).join("")}</tbody></table>`;
    },
    setSelected(id) {
      selectedId = id;
      el.querySelectorAll("tr[data-row]").forEach((tr) => {
        const on = tr.dataset.row === id;
        tr.classList.toggle("is-selected", on);
        const b = tr.querySelector("button");
        if (on) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
      });
    },
  };
}
