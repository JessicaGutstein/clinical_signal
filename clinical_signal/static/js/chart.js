// Weekly admissions for the past 12 months, drawn so it explains itself:
// both axes are labelled, the usual range is a grey band named on the chart, the
// history is a quiet grey line, and the last four weeks are a bold red line.

import { int, shortDate } from "./format.js";

export function renderChart(el, rows) {
  // Drawn at the panel's real width, so the labels stay at their true size.
  const W = Math.max(300, Math.round(el.clientWidth) || 400), H = 270, m = { top: 30, right: 16, bottom: 46, left: 54 };
  const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
  const x = d3.scaleLinear().domain([0, rows.length - 1]).range([0, iw]);
  const yMax = d3.max(rows, (d) => Math.max(d.value, d.high ?? 0)) || 1;
  const y = d3.scaleLinear().domain([0, yMax]).nice(4).range([ih, 0]);
  const pts = rows.map((d, i) => ({ ...d, i }));
  const banded = pts.filter((d) => d.expected != null);
  const first = rows.findIndex((d) => d.in_window), last = rows.length - 1;

  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Line chart of member admissions per week over the past 12 months. The last four weeks are drawn in red. A table of the same numbers follows."></svg><div class="chart-tip"></div>`;
  const tip = el.querySelector(".chart-tip");
  const g = d3.select(el).select("svg").append("g").attr("transform", `translate(${m.left},${m.top})`);

  // Vertical axis: gridlines, numbers, and what they count.
  const ticks = y.ticks(4).filter(Number.isInteger);
  g.append("g").attr("class", "grid").selectAll("line").data(ticks).join("line").attr("x1", 0).attr("x2", iw).attr("y1", y).attr("y2", y);
  g.append("g").attr("class", "axis").selectAll("text").data(ticks).join("text")
    .attr("x", -9).attr("y", (d) => y(d) + 4.5).attr("text-anchor", "end").text((d) => int(d));
  g.append("text").attr("class", "axis-title").attr("transform", `translate(${-40},${ih / 2}) rotate(-90)`).attr("text-anchor", "middle").text("Member admissions per week");

  // Horizontal axis: a label at the first week of every second month.
  const months = [];
  rows.forEach((d, i) => {
    const date = new Date(`${d.week_start}T00:00:00`), prev = i ? new Date(`${rows[i - 1].week_start}T00:00:00`) : null;
    if (!prev || prev.getMonth() !== date.getMonth()) months.push({ i, date });
  });
  g.append("g").attr("class", "axis").selectAll("text")
    .data(months.filter((_, k) => k % 2 === (months.length - 1) % 2)).join("text")
    .attr("x", (d) => x(d.i)).attr("y", ih + 19).attr("text-anchor", "middle")
    .text((d) => d.date.toLocaleDateString("en-US", { month: "short" }));
  g.append("text").attr("class", "axis-title").attr("x", iw / 2).attr("y", ih + 40).attr("text-anchor", "middle").text("Month (past 12 months)");

  // The usual range, named on the chart where the band is easiest to see.
  if (banded.length) {
    g.append("path").attr("class", "band").attr("d",
      d3.area().x((d) => x(d.i)).y0((d) => y(d.low)).y1((d) => y(d.high)).curve(d3.curveMonotoneX)(banded));
    const at = banded[Math.floor(banded.length * 0.42)];
    g.append("text").attr("class", "band-label").attr("x", x(at.i)).attr("y", Math.max(12, y(at.high) - 7)).attr("text-anchor", "middle").text("Normal range");
  }

  // History in grey; the last four weeks in bold red, joined to the week before them.
  const line = d3.line().x((d) => x(d.i)).y((d) => y(d.value));
  g.append("path").attr("class", "history").attr("d", line(pts.slice(0, first > 0 ? first : pts.length)));
  if (first >= 0) {
    const recent = pts.slice(Math.max(first - 1, 0));
    g.append("path").attr("class", "recent").attr("d", line(recent));
    g.selectAll("circle.pt").data(pts.slice(first)).join("circle").attr("class", "pt").attr("cx", (d) => x(d.i)).attr("cy", (d) => y(d.value)).attr("r", 4.5);
    const peak = pts.slice(first).reduce((a, b) => (b.value > a.value ? b : a));
    g.append("text").attr("class", "recent-label").attr("x", iw + 4).attr("y", Math.max(-12, y(peak.value) - 13)).attr("text-anchor", "end").text("Last 4 weeks");
  }

  // Hover: a marker and that week's numbers in words.
  const cross = g.append("line").attr("class", "cross").attr("y1", 0).attr("y2", ih).style("display", "none");
  g.append("rect").attr("x", -6).attr("y", -8).attr("width", iw + 12).attr("height", ih + 8).attr("fill", "transparent")
    .on("mousemove", (e) => {
      const [mx] = d3.pointer(e);
      const i = Math.max(0, Math.min(last, Math.round(x.invert(mx)))), d = rows[i];
      cross.style("display", null).attr("x1", x(i)).attr("x2", x(i));
      const range = d.expected == null ? "No earlier years to compare" : `Normal range: ${int(d.low)} to ${int(d.high)}`;
      tip.innerHTML = `<strong>Week of ${shortDate(d.week_start)}</strong><br>${int(d.value)} ${Math.round(d.value) === 1 ? "admission" : "admissions"}<br>${range}`;
      tip.classList.add("is-on");
      const scale = el.clientWidth / W, tw = tip.offsetWidth;
      let left = (m.left + x(i)) * scale + 10;
      if (left + tw > el.clientWidth) left = (m.left + x(i)) * scale - tw - 10;
      tip.style.left = `${Math.max(0, left)}px`;
      tip.style.top = `${Math.max(0, (m.top + y(d.value)) * scale - 58)}px`;
    })
    .on("mouseleave", () => { cross.style("display", "none"); tip.classList.remove("is-on"); });
}

// One line under the chart, saying what the band and the two lines mean.
export const chartNote = `<p class="chart-note"><b>How to read this.</b> The grey band is the normal range: where weekly member admissions usually fall here, based on the same weeks in earlier years. The grey line is the past year. The red line is the last four weeks, the period this hotspot covers. Red above the band means more member admissions than usual.</p>`;
