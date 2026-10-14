// Small formatting helpers shared by every part of the page.

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const int = (n) => (n == null ? "n/a" : Math.round(n).toLocaleString("en-US"));

export const signed = (n) => {
  if (n == null) return "";
  const v = Math.round(n);
  return v > 0 ? `+${v.toLocaleString("en-US")}` : v < 0 ? `−${Math.abs(v).toLocaleString("en-US")}` : "0";
};

// A rounded amount for a headline: $2.4M, $189K.
export const money = (n) => {
  if (n == null) return "n/a";
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `$${Math.round(n / 1e3)}K`;
  return `$${Math.round(n)}`;
};
// The exact amount, for showing how a figure was worked out: $13,498.
export const dollars = (n) => (n == null ? "n/a" : `$${Math.round(n).toLocaleString("en-US")}`);

export const pct = (x) => `${Math.round(x * 100)}%`;

const asDate = (iso) => new Date(`${iso}T00:00:00`);
export const shortDate = (iso) => asDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
export const longDate = (iso) => asDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

export const plural = (n, one, many) => `${n} ${n === 1 ? one : many ?? `${one}s`}`;

// Place in the list: a red number for a top hotspot, grey for the rest.
// The words for a screen reader mean colour is never the only cue.
export const rankBadge = (a) =>
  `<span class="badge rank ${a.priority}"><span class="sr">${a.priority === "high" ? "Top hotspot, rank" : "Hotspot, rank"} </span>${a.rank}</span>`;

// ---- Explanations on demand ----
// Anything calculated can be opened up: hover over it, or tab to it, and a small
// box says what it means and how it was worked out. `control` is the button's inner
// HTML; the box is tied to it for screen readers and Escape closes it.
export const withTip = (id, control, tipHtml, cls = "") =>
  `<span class="has-tip ${cls}"><button type="button" class="tip-btn" aria-describedby="${id}">${control}</button>` +
  `<span class="tip" role="tooltip" id="${id}">${tipHtml}</span></span>`;

// ---- Mini bar: a count against its expected value, on a scale shared by the table ----
// The hollow part runs up to expected and the solid part is the amount above it,
// so the two read apart by shape as well as colour.
export function miniBar(d, max, flagged = false) {
  const obs = Math.max(d.observed ?? 0, 0), exp = d.expected;
  const w = (v) => `${Math.max(0, Math.min(100, (v / (max || 1)) * 100)).toFixed(1)}%`;
  if (exp == null) return `<span class="mbar" aria-hidden="true"><i class="base end" style="width:${w(obs)}"></i></span>`;
  const base = Math.min(obs, exp), over = Math.max(obs - exp, 0);
  const parts = [];
  if (base > 0) parts.push(`<i class="base${over > 0 ? "" : " end"}" style="width:${w(base)}"></i>`);
  if (over > 0) parts.push(`<i class="over end" style="width:${w(over)}"></i>`);
  const tick = obs < exp ? `<i class="tick" style="left:${w(exp)}"></i>` : "";
  return `<span class="mbar${flagged ? " is-flagged" : ""}" aria-hidden="true">${parts.join("")}${tick}</span>`;
}

// A table of rows, each with a name, a mini bar, "count vs expected", and the difference.
// rows: [{ name, title?, display, facilityId? }]; a row with a facilityId opens that hospital.
export function barTable(rows, { nameHeader, caption, flagged = false }) {
  const max = Math.max(1, ...rows.map((r) => Math.max(r.display.observed ?? 0, r.display.expected ?? 0)));
  const body = rows.map((r) => {
    const d = r.display;
    const diff = d.excess == null ? "" : Math.abs(d.excess) < 1 ? "0" : signed(d.excess);
    const hint = r.title ? ` title="${esc(r.title)}"` : "";
    const name = r.facilityId
      ? `<button type="button" class="bt-link" data-facility="${esc(r.facilityId)}"${hint}>${esc(r.name)}</button>`
      : esc(r.name);
    const vs = d.expected == null ? int(d.observed) : `${int(d.observed)} vs ${int(d.expected)}`;
    return `<tr><th scope="row">${name}</th><td class="bt-bar">${miniBar(d, max, flagged)}</td>
      <td class="num">${vs}</td><td class="num diff">${diff}</td></tr>`;
  }).join("");
  return `<table class="bt"><caption class="sr">${esc(caption)}</caption>
    <thead><tr><th scope="col">${esc(nameHeader)}</th><td class="bt-bar"></td>
    <th scope="col" class="num c-count">Reported vs expected</th><th scope="col" class="num c-diff">Above</th></tr></thead><tbody>${body}</tbody></table>`;
}

// ---- Diagnosis codes ----
// A slice is named by its facilities (null for every facility) and its diagnosis
// groups (null for every group). The key is used to ask the server for its codes.
export const codesKey = (facilityIds, diagnoses) => JSON.stringify([facilityIds, diagnoses]);

// The list inside the "Top diagnosis codes" drop-down. `data` is null while it loads.
// Each code can be hovered or tabbed to for a plain explanation of what it means.
export function codeList(data) {
  if (!data) return `<p class="loading">Loading codes…</p>`;
  if (data.error) return `<p class="loading">The codes could not be loaded.</p>`;
  if (!data.codes.length) return `<p class="note">No member admissions reported here in the last ${data.window_days} days.</p>`;
  const usual = data.usual_basis === "own" ? "its share here over the past year" : "its share across the whole plan, because there is little history here";
  const several = data.n_groups > 1;
  const items = data.codes.map((c, i) => `<li>${withTip(`code-tip-${i}`,
    `<span class="code">${esc(c.code)}</span><span class="code-name">${esc(c.name)}</span><span class="code-n">${int(c.count)}</span>
     <span class="code-share">${pct(c.share)} of admissions now, usually ${pct(c.usual_share)}</span>`,
    `${several ? `<b>${esc(c.group)}.</b> ` : ""}${esc(c.meaning)}`, "code-row")}</li>`).join("");
  const shown = data.n_codes > data.codes.length ? `The ${data.codes.length} most common of ${data.n_codes} codes` : "The codes";
  const across = data.all_groups ? ", across all diagnosis groups" : several ? `, across ${data.n_groups} diagnosis groups` : "";
  return `<p class="note">ICD-10 codes are the standard codes facilities use to record a diagnosis. ${shown} among the ${int(data.reported)} member ${data.reported === 1 ? "admission" : "admissions"} reported here in the last ${data.window_days} days${across}:</p>
    <ul class="code-list">${items}</ul>
    <p class="note">"Usually" is ${usual}. Hover over a code, or tab to it, to see what it means.</p>`;
}
