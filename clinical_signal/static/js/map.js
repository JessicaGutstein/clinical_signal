// The bubble map. Every facility sits at its real location; hotspots are red
// bubbles sized by member admissions above expected, everything else is a grey dot.
// Nothing here depends on colour alone: a hotspot is also larger and carries its
// rank, and the Table view gives the same information as text.

import { esc, int, signed } from "./format.js";

const AREA_LABELS = [
  ["Manhattan", -74.016, 40.772], ["Bronx", -73.858, 40.828], ["Brooklyn", -73.925, 40.628],
  ["Queens", -73.775, 40.688], ["Staten Island", -74.148, 40.575], ["Nassau", -73.585, 40.752],
  ["Westchester", -73.745, 41.135], ["New Jersey", -74.215, 40.835], ["Connecticut", -73.52, 41.155],
];
const WAVE_MAX_KM = 10; // beyond this a single circle would swallow unrelated facilities
const DOT_R = 3.4;
const HIT_R = 12; // every bubble has at least a 24px target

export function createMap(root, legendEl, handlers) {
  const svg = d3.select(root).select("svg");
  const tooltip = root.querySelector(".tooltip");
  svg.append("rect").attr("class", "water").attr("width", "100%").attr("height", "100%");
  const gLand = svg.append("g").attr("class", "land");
  const gAreas = svg.append("g").attr("class", "areas");
  const gWaves = svg.append("g").attr("class", "waves");
  const gFacs = svg.append("g").attr("class", "facs");
  const gLabels = svg.append("g").attr("class", "labels");

  let geo = null, facilities = [], alertById = new Map(), waves = [];
  let width = 0, height = 0, projection = null, pxPerKm = 1;
  let t = d3.zoomIdentity, view = "region";
  let activeIds = null, activeWaveId = null, selectedId = null;
  // Keyboard: the bubbles are one stop in the tab order, and the arrow keys move
  // between them (hotspots first), so nobody has to tab through 100 facilities.
  let navOrder = [], navId = null;
  const rScale = d3.scaleSqrt().range([0, 36]);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const zoom = d3.zoom().scaleExtent([0.8, 16]).on("zoom", (e) => { t = e.transform; draw(); });
  svg.call(zoom).on("dblclick.zoom", null);
  svg.on("click", () => handlers.onBackgroundClick());

  const pos = (f) => t.apply([f._x, f._y]);

  // ------------------------------------------------------------- data
  function setGeo(g) { geo = g; if (facilities.length) { layout(); draw(); } }

  function setData(overview) {
    alertById = new Map(overview.alerts.map((a) => [a.id, a]));
    facilities = overview.facilities.map((f) => {
      const ids = f.status === "high" ? f.high_alerts : f.low_alerts;
      const own = ids.map((id) => alertById.get(id));
      const rollup = own.find((a) => a.kind === "facility");
      return {
        ...f,
        _rank: own.length ? Math.min(...own.map((a) => a.rank)) : null,
        _badge: rollup ? rollup.members.length : own.length > 1 ? own.length : null,
      };
    });
    waves = overview.alerts.filter((a) => a.kind === "wave");
    const maxExcess = d3.max(facilities, (f) => f.excess) || 0;
    rScale.domain([0, Math.max(maxExcess, 40)]);
    facilities.forEach((f) => {
      f._r = f.status === "none" ? DOT_R : Math.max(rScale(f.excess), f.status === "high" ? 10 : 7);
    });
    activeIds = null; activeWaveId = null; selectedId = null;
    const tier = { high: 0, low: 1, none: 2 };
    navOrder = [...facilities].sort((a, b) => tier[a.status] - tier[b.status] || (a._rank ?? 0) - (b._rank ?? 0) || a.name.localeCompare(b.name)).map((f) => f.id);
    navId = navOrder[0] ?? null;
    if (geo) { layout(); draw(); }
    renderLegend(legendEl, rScale);
  }

  // ----------------------------------------------------------- layout
  function layout() {
    const box = root.getBoundingClientRect();
    width = box.width; height = box.height;
    if (!width || !height) return;
    svg.attr("viewBox", `0 0 ${width} ${height}`);
    const pad = Math.min(width, height) * 0.07;
    const points = { type: "MultiPoint", coordinates: facilities.map((f) => [f.lon, f.lat]) };
    projection = d3.geoMercator().fitExtent([[pad, pad], [width - pad, height - pad]], points);
    gLand.selectAll("path").data(geo.features).join("path")
      .attr("class", (d) => d.properties.kind).attr("d", d3.geoPath(projection));
    facilities.forEach((f) => { [f._x, f._y] = projection([f.lon, f.lat]); });
    const a = projection([-73.9, 40.7]), b = projection([-73.9, 40.7 + 1 / 110.574]);
    pxPerKm = Math.abs(a[1] - b[1]);
    const byId = new Map(facilities.map((f) => [f.id, f]));
    waves.forEach((w) => {
      w._members = w.facility_ids.map((id) => byId.get(id));
      w._circle = d3.packEnclose(w._members.map((f) => ({ x: f._x, y: f._y, r: 0 })));
      w._drawn = w._circle.r / pxPerKm <= WAVE_MAX_KM;
    });
    zoom.translateExtent([[-width * 0.6, -height * 0.6], [width * 1.6, height * 1.6]]);
    svg.call(zoom.transform, viewTransform(view));
  }

  function viewTransform(which) {
    if (which === "region") return d3.zoomIdentity;
    const city = facilities.filter((f) => f.borough !== "Outside NYC");
    const xs = d3.extent(city, (f) => f._x), ys = d3.extent(city, (f) => f._y);
    const k = Math.min(16, 0.86 / Math.max((xs[1] - xs[0]) / width, (ys[1] - ys[0]) / height));
    return d3.zoomIdentity
      .translate(width / 2 - (k * (xs[0] + xs[1])) / 2, height / 2 - (k * (ys[0] + ys[1])) / 2)
      .scale(k);
  }

  function setView(which) {
    view = which;
    const target = viewTransform(which);
    (reduceMotion ? svg : svg.transition().duration(550)).call(zoom.transform, target);
  }

  function zoomBy(factor) {
    (reduceMotion ? svg : svg.transition().duration(250)).call(zoom.scaleBy, factor);
  }

  // ------------------------------------------------------------- draw
  function draw() {
    if (!projection) return;
    gLand.attr("transform", t);

    gAreas.selectAll("text").data(AREA_LABELS).join("text").attr("class", "area-label")
      .attr("x", (d) => t.apply(projection([d[1], d[2]]))[0])
      .attr("y", (d) => t.apply(projection([d[1], d[2]]))[1])
      .text((d) => d[0]);

    // Rolled-up waves: one circle around the member facilities.
    const drawn = waves.filter((w) => w._drawn);
    const wave = gWaves.selectAll("g.wave").data(drawn, (d) => d.id).join((enter) => {
      const g = enter.append("g").attr("tabindex", 0).attr("role", "button");
      g.append("circle");
      g.append("text").attr("class", "wave-label");
      g.on("click", (e, d) => { e.stopPropagation(); handlers.onWaveClick(d.id); })
        .on("keydown", (e, d) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handlers.onWaveClick(d.id); } })
        .on("mouseenter", (e, d) => { showTip(e, waveTip(d)); handlers.onWaveHover(d.id); })
        .on("mousemove", moveTip)
        .on("mouseleave", () => { hideTip(); handlers.onWaveHover(null); });
      return g;
    });
    wave.attr("class", (d) => `wave ${d.priority}${d.id === activeWaveId ? " is-active" : ""}`)
      .attr("aria-label", (d) => `${d.title}, ${d.subtitle}`)
      .each(function (d) {
        const [cx, cy] = t.apply([d._circle.x, d._circle.y]);
        const r = d._circle.r * t.k + d3.max(d._members, (f) => f._r) + 9;
        d3.select(this).select("circle").attr("cx", cx).attr("cy", cy).attr("r", r);
        d3.select(this).select("text").attr("x", cx).attr("y", cy - r - 7).text(d.subtitle);
        d._labelBox = [cx - d.subtitle.length * 3.8, cy - r - 21, cx + d.subtitle.length * 3.8, cy - r - 3];
      });
    gWaves.classed("has-active", !!(activeIds || activeWaveId));

    // Facilities: quiet dots underneath, biggest bubbles first so small ones stay on top.
    const order = { none: 0, low: 1, high: 2 };
    const sorted = [...facilities].sort((a, b) => order[a.status] - order[b.status] || b._r - a._r);
    const fac = gFacs.selectAll("g.fac").data(sorted, (d) => d.id).join((enter) => {
      const g = enter.append("g");
      g.append("circle").attr("class", "hit");
      g.append("circle").attr("class", "dot");
      g.on("click", (e, d) => { e.stopPropagation(); handlers.onFacilityClick(d.id); })
        .on("keydown", (e, d) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handlers.onFacilityClick(d.id); return; }
          const i = navOrder.indexOf(d.id);
          const to = { ArrowRight: i + 1, ArrowDown: i + 1, ArrowLeft: i - 1, ArrowUp: i - 1, Home: 0, End: navOrder.length - 1 }[e.key];
          if (to === undefined) return;
          e.preventDefault();
          moveFocus(navOrder[Math.max(0, Math.min(navOrder.length - 1, to))]);
        })
        .on("focus", (e, d) => { navId = d.id; gFacs.selectAll("g.fac").attr("tabindex", (x) => (x.id === navId ? 0 : -1)); })
        .on("mouseenter focus.tip", (e, d) => { showTip(e, facilityTip(d)); handlers.onFacilityHover(d.id); })
        .on("mousemove", moveTip)
        .on("mouseleave blur", () => { hideTip(); handlers.onFacilityHover(null); });
      return g;
    });
    fac.order()
      .attr("class", (d) => ["fac", d.status,
        activeIds && activeIds.has(d.id) ? "is-active" : "", d.id === selectedId ? "is-selected" : ""].join(" "))
      .attr("transform", (d) => `translate(${pos(d)})`)
      .attr("tabindex", (d) => (d.id === navId ? 0 : -1))
      .attr("role", "button")
      .attr("aria-label", (d) => d.status === "none" ? `${d.name}, no hotspot`
        : `${d.name}, ${d.status === "high" ? "top hotspot" : "hotspot"}, rank ${d._rank}, ${signed(d.excess)} member admissions above expected`);
    fac.select(".hit").attr("r", (d) => Math.max(d._r + 3, HIT_R));
    fac.select(".dot").attr("r", (d) => (d.id === selectedId && d.status === "none" ? 6 : d._r));
    fac.each(function (d) {
      const g = d3.select(this);
      const showRank = d.status === "high";
      g.selectAll("text.rank").data(showRank ? [d] : []).join("text").attr("class", "rank").text(d._rank);
      const badge = g.selectAll("g.count").data(d.status === "high" && d._badge ? [d] : []).join((enter) => {
        const b = enter.append("g").attr("class", "count");
        b.append("circle").attr("r", 9.5);
        b.append("text");
        return b;
      });
      badge.attr("transform", `translate(${d._r * 0.74}, ${-d._r * 0.74})`).select("text").text(d._badge);
    });
    gFacs.classed("has-active", !!activeIds);

    placeLabels();
  }

  function moveFocus(id) {
    const node = gFacs.selectAll("g.fac").filter((d) => d.id === id).node();
    if (node) node.focus();
  }

  // Name the hotspots, skipping any label that would collide with a bubble or another label.
  function placeLabels() {
    const high = facilities.filter((f) => f.status === "high").sort((a, b) => b._r - a._r);
    const taken = high.map((f) => { const [x, y] = pos(f); return [x - f._r, y - f._r, x + f._r, y + f._r]; });
    waves.filter((w) => w._drawn && w._labelBox).forEach((w) => taken.push(w._labelBox));
    const hits = (b) => taken.some((o) => b[0] < o[2] && b[2] > o[0] && b[1] < o[3] && b[3] > o[1]);
    const placed = [];
    for (const f of high) {
      const [x, y] = pos(f);
      if (x < 0 || x > width || y < 0 || y > height) continue;
      const w = f.short_name.length * 7 + 6, r = f._r;
      const options = [
        { x: x + r + 5, y: y + 4, anchor: "start", box: [x + r + 3, y - 9, x + r + 5 + w, y + 8] },
        { x: x - r - 5, y: y + 4, anchor: "end", box: [x - r - 5 - w, y - 9, x - r - 3, y + 8] },
        { x, y: y + r + 15, anchor: "middle", box: [x - w / 2, y + r + 2, x + w / 2, y + r + 19] },
        { x, y: y - r - 6, anchor: "middle", box: [x - w / 2, y - r - 20, x + w / 2, y - r - 3] },
      ];
      const spot = options.find((o) => !hits(o.box) && o.box[0] > 2 && o.box[2] < width - 2);
      if (spot) { taken.push(spot.box); placed.push({ f, ...spot }); }
    }
    gLabels.selectAll("text").data(placed, (d) => d.f.id).join("text")
      .attr("class", "fac-label")
      .attr("x", (d) => d.x).attr("y", (d) => d.y).attr("text-anchor", (d) => d.anchor)
      .text((d) => d.f.short_name);
  }

  // ---------------------------------------------------------- tooltip
  function alertLine(f, a) {
    // In a group, a facility's own figures matter more than the group's.
    const own = a.kind === "wave" ? a.members.find((m) => m.facility_id === f.id) : null;
    const d = (own || a).display, period = (own || a).period;
    const nums = d.expected == null ? `${int(d.observed)} member admissions`
      : `${int(d.observed)} vs ${int(d.expected)} expected, ${signed(d.excess)}`;
    const when = period === "last 28 days" ? "" : ` (${period})`;
    const where = a.kind === "wave" ? `<br><span class="tt-sub">Part of: ${esc(a.subtitle)}</span>` : "";
    const tier = a.priority === "high" ? `Top hotspot, rank ${a.rank}` : `Hotspot, rank ${a.rank}`;
    return `<div class="tt-line ${a.priority}"><i></i><div><strong>${esc(a.title)}</strong><br>` +
      `<span class="tt-nums">${nums}${when}</span><br><span class="tt-sub">${tier}</span>${where}</div></div>`;
  }

  function facilityTip(f) {
    const head = `<strong>${esc(f.name)}</strong><br><span class="tt-sub">${esc(f.type)}, ${esc(f.area)}<br>${esc(f.system)} · ${esc(f.network)}</span>`;
    const ids = [...f.high_alerts, ...f.low_alerts];
    if (!ids.length) {
      const d = f.display;
      const nums = d.expected == null ? `${int(d.observed)} member admissions` : `${int(d.observed)} member admissions vs ${int(d.expected)} expected`;
      return `${head}<div class="tt-line"><i></i><div>No hotspots here<br><span class="tt-nums">Last 28 days: ${nums}</span></div></div>`;
    }
    return head + ids.map((id) => alertLine(f, alertById.get(id))).join("");
  }

  function waveTip(w) {
    const d = w.display;
    return `<strong>${esc(w.title)}</strong><br><span class="tt-sub">${esc(w.subtitle)}</span>` +
      `<div class="tt-line ${w.priority}"><i></i><div><span class="tt-nums">${int(d.observed)} vs ${int(d.expected)} expected, ${signed(d.excess)}</span></div></div>`;
  }

  function showTip(e, html) { tooltip.innerHTML = html; tooltip.classList.add("is-on"); moveTip(e); }
  // Returns true when a tooltip was showing, so Escape can dismiss it first.
  function hideTip() { const was = tooltip.classList.contains("is-on"); tooltip.classList.remove("is-on"); return was; }
  function moveTip(e) {
    const box = root.getBoundingClientRect();
    let px = e.clientX, py = e.clientY;
    if (px === undefined || (px === 0 && py === 0)) { // keyboard focus: anchor to the element
      const r = e.currentTarget.getBoundingClientRect();
      px = r.left + r.width / 2; py = r.top;
    }
    const tw = tooltip.offsetWidth, th = tooltip.offsetHeight;
    let x = px - box.left + 14, y = py - box.top + 14;
    if (x + tw > box.width - 8) x = px - box.left - tw - 14;
    if (y + th > box.height - 8) y = py - box.top - th - 14;
    tooltip.style.left = `${Math.max(8, x)}px`;
    tooltip.style.top = `${Math.max(8, y)}px`;
  }

  // ------------------------------------------------------------ state
  function setHighlight({ facilityIds = null, waveId = null, selected = null }) {
    activeIds = facilityIds ? new Set(facilityIds) : null;
    activeWaveId = waveId;
    selectedId = selected;
    draw();
  }

  new ResizeObserver(() => { if (geo && facilities.length) { layout(); draw(); } }).observe(root);

  return { setGeo, setData, setHighlight, setView, zoomBy, hideTip };
}

// ---------------------------------------------------------------- legend
// A strip docked under the map, so it never covers a bubble.
function renderLegend(el, rScale) {
  const max = rScale.domain()[1];
  const steps = [5, 10, 25, 50, 100, 150, 300, 500];
  const big = steps.filter((s) => s <= max).pop() || 10;
  const mid = steps.filter((s) => s <= big / 4).pop();
  const small = mid ? steps.filter((s) => s <= mid / 4).pop() : null;
  const values = [big, mid, small].filter(Boolean);
  const R = rScale(big), w = R * 2 + 48, h = R * 2 + 12;
  const circles = values.map((v) => {
    const r = rScale(v), cy = h - 2 - r;
    return `<circle cx="${R + 1}" cy="${cy}" r="${r}" fill="none" stroke="#47586a" stroke-width="1"/>` +
      `<line x1="${R + 1}" x2="${R * 2 + 8}" y1="${cy - r}" y2="${cy - r}" stroke="#6b7986" stroke-width="1"/>` +
      `<text x="${R * 2 + 11}" y="${cy - r + 4.5}" font-size="13" fill="#47586a">+${v}</text>`;
  }).join("");
  // Open by default; on a short window it starts closed so the map keeps its height.
  const closed = el.dataset.ready ? el.classList.contains("is-closed") : window.innerHeight < 800;
  el.dataset.ready = "1";
  el.classList.toggle("is-closed", closed);
  const icon = (svg, text) => `<div class="legend-row"><svg width="22" height="22" aria-hidden="true">${svg}</svg>${text}</div>`;
  el.innerHTML = `
    <h2 class="legend-title"><button type="button" class="legend-toggle" aria-expanded="${!closed}">How to read the map<span>${closed ? "Show" : "Hide"}</span></button></h2>
    <div class="legend-body">
      <div class="legend-group">
        <h3>Bubble size: member admissions above expected</h3>
        <svg width="${w}" height="${h}" role="img" aria-label="Larger bubbles mean more member admissions above expected">${circles}</svg>
      </div>
      <div class="legend-group legend-symbols">
        ${icon(`<circle cx="11" cy="11" r="10" fill="#c72e2b"/><text x="11" y="15.5" font-size="13" font-weight="700" text-anchor="middle" fill="#fff">1</text>`, "Red, numbered: top hotspot and its rank")}
        ${icon(`<circle cx="11" cy="11" r="7.5" fill="#cdd4d8" stroke="#5f6c78" stroke-width="1.5"/>`, "Grey bubble: a smaller hotspot")}
        ${icon(`<circle cx="11" cy="11" r="3.4" fill="#66737f"/>`, "Small dot: facility with no hotspot")}
        ${icon(`<circle cx="11" cy="11" r="9.5" fill="#c72e2b" fill-opacity=".08" stroke="#c72e2b" stroke-width="1.6" stroke-dasharray="4 3"/>`, "Dashed circle: same diagnosis at 3+ nearby facilities")}
        ${icon(`<circle cx="11" cy="11" r="9.5" fill="#fff" stroke="#14212d" stroke-width="1.4"/><text x="11" y="15.5" font-size="13" font-weight="700" text-anchor="middle" fill="#14212d">4</text>`, "White badge: diagnosis groups involved there")}
        ${icon(`<rect x="2" y="5" width="18" height="12" rx="3" fill="#cfe2f0" stroke="#6b7986" stroke-width="1"/>`, "Blue: water")}
      </div>
    </div>`;
  el.querySelector(".legend-toggle").onclick = (e) => {
    const nowClosed = el.classList.toggle("is-closed");
    e.currentTarget.setAttribute("aria-expanded", String(!nowClosed));
    e.currentTarget.querySelector("span").textContent = nowClosed ? "Show" : "Hide";
  };
}
