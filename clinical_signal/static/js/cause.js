// The "What's driving it" tab: part two.
// For a hotspot it lists up to three possible causes found in outside sources, each
// with a strength label, the items behind it, and three buttons for a person to
// confirm it, reject it, or say they are not sure. Nothing here is a conclusion
// until a person confirms it. When nothing fits, the tab says so plainly.

import { esc, int, longDate, withTip, plural } from "./format.js";

const STRENGTH = {
  strong: { label: "Strong match", bars: 3, means: "The outside items fit this hotspot closely on place, timing and diagnosis." },
  moderate: { label: "Moderate match", bars: 2, means: "The outside items fit this hotspot on most counts, but not all." },
  weak: { label: "Weak match", bars: 1, means: "The outside items fit this hotspot only loosely. Treat this as a long shot." },
};
const DECISIONS = [
  { id: "confirmed", label: "Confirm", done: "Confirmed" },
  { id: "rejected", label: "Reject", done: "Rejected" },
  { id: "unsure", label: "Not sure", done: "Marked not sure" },
];
const NAME_KEY = "clinical-signal-reviewer";

// The reviewer's name is a convenience kept in this browser only. The page works without it.
export function savedName() { try { return localStorage.getItem(NAME_KEY) || ""; } catch { return ""; } }
export function saveName(name) { try { localStorage.setItem(NAME_KEY, name); } catch { /* private window: fine */ } }

const when = (iso) => {
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} at ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
};
const itemDates = (it) => (it.ends && it.ends !== it.starts ? `${longDate(it.starts)} to ${longDate(it.ends)}` : longDate(it.starts));

// What the outside sources are, in words. Shown when no hotspot is selected.
function sourcesNote(outside) {
  if (!outside || !outside.total) return `<p class="d-quiet">No outside items are loaded, so this tab has nothing to read.</p>`;
  const rows = outside.by_type.map((t) => `<div><dt>${esc(t.label)}</dt><dd>${int(t.count)} items</dd></div>`).join("");
  return `<dl class="facts">${rows}</dl>
    <p class="d-hint">${int(outside.total)} items in all. They are invented for this prototype and kept apart from the admissions data: finding hotspots never uses them.</p>
    <p class="d-text"><a class="src-all" href="/external/" target="_blank" rel="noopener">Browse all ${int(outside.total)} outside items${NEW_TAB}</a></p>`;
}

export function causeIntro(meta, pick) {
  return `<section class="d-block"><p class="d-text"><strong>${esc(pick)}</strong></p>
      <p class="d-text">A hotspot says where something unusual is happening. This tab looks outside the plan's own data for what may be behind it.</p></section>
    <section class="d-block"><h4>What it reads</h4>${sourcesNote(meta && meta.outside)}</section>
    <section class="d-block"><h4>How a possible cause is found</h4>
      <ul class="plain"><li>Fixed rules keep only the outside items that fit the hotspot on three tests: the same place, timing that comes before or with the rise, and the same kind of admission.</li>
      <li>AI then reads those few items and explains, in plain words, how each could lead to the admissions. It can lower a rating but never raise one.</li>
      <li>A person confirms or rejects each possible cause. Only a confirmed cause is passed on to “Who can act”.</li></ul></section>`;
}

export const causeLoading = () => `<div data-causes><section class="d-block"><p class="loading">Reading outside sources…</p></section></div>`;

function strengthBadge(c, i) {
  const s = STRENGTH[c.strength];
  const bars = [1, 2, 3].map((n) => `<i class="${n <= s.bars ? "on" : ""}"></i>`).join("");
  const lines = c.parts.map((p) => `<li><b>${esc(p.test)}${p.of ? ` (${p.points > 0 ? p.points : `−${Math.abs(p.points)}`} of ${p.of})` : ""}.</b> ${esc(p.text)}</li>`).join("");
  const lowered = c.lowered_by_ai ? ` The rules rated this ${esc(c.rule_strength)}; AI lowered it after reading the items.` : "";
  return withTip(`cause-tip-${i}`,
    `<span class="strength-bars" aria-hidden="true">${bars}</span><span class="strength-word">${s.label}</span><span class="fig-how">Why this rating?</span>`,
    `${s.means}${lowered} It scored ${c.score} of ${c.max_score}: 6 or more is strong, 5 is moderate, less is weak.<ul class="tip-list">${lines}</ul>`,
    `strength is-${c.strength}`);
}

// An outside item is shown as a link to its own page, which opens in a new tab, the way a
// real version would link to the news site or the notice. The text is not repeated here.
const NEW_TAB = `<span class="src-new" aria-hidden="true">&#8599;</span><span class="sr"> (opens in a new tab)</span>`;
const itemLink = (it, cls) => `<a class="${cls}" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title)}${NEW_TAB}</a>`;

function sourceItem(it) {
  return `<div class="src">${itemLink(it, "src-title")}
      <span class="src-meta">${esc(it.source_label)} · ${esc(it.source_name)} · ${esc(itemDates(it))}</span></div>`;
}

export function reviewBox(c, i) {
  const r = c.review;
  const done = r ? DECISIONS.find((d) => d.id === r.decision) : null;
  const status = r
    ? `<p class="rv-status is-${esc(r.decision)}"><span class="rv-mark" aria-hidden="true">${r.decision === "confirmed" ? "&#10003;" : r.decision === "rejected" ? "&times;" : "?"}</span>
        <span><b>${done.done}</b> by ${esc(r.reviewer)} on ${esc(when(r.at))}.${r.decision === "confirmed" ? " It will be passed on to “Who can act”." : ""}</span></p>`
    : `<p class="rv-status"><span class="rv-mark" aria-hidden="true">&ndash;</span><span><b>Not reviewed yet.</b> It is a suggestion until a person decides.</span></p>`;
  const buttons = DECISIONS.map((d) =>
    `<button type="button" class="rv-btn" data-review="${d.id}" aria-pressed="${r?.decision === d.id}">${d.label}</button>`).join("");
  return `<div class="rv" data-topic="${esc(c.topic)}">${status}
      <label class="rv-note" for="rv-note-${i}">Note (optional)</label>
      <input class="rv-input" id="rv-note-${i}" data-note type="text" maxlength="500" value="${esc(r?.note || "")}" placeholder="Why you decided this">
      <div class="rv-btns" role="group" aria-label="Your decision on: ${esc(c.label)}">${buttons}</div></div>`;
}

function causeCard(c, i) {
  const more = c.n_items > c.items.length ? `<p class="d-hint">${plural(c.n_items - c.items.length, "more item")} like these.</p>` : "";
  const agree = c.n_source_types > 1 ? ` from ${c.n_source_types} kinds of source` : "";
  return `<li class="cause">
      <div class="cause-head"><span class="cause-rank" aria-hidden="true">${c.rank}</span><h5><span class="sr">Possible cause ${c.rank}: </span>${esc(c.label)}</h5></div>
      ${strengthBadge(c, i)}
      <p class="d-text">${esc(c.why)}</p>
      <p class="d-source">${c.written_by === "claude" ? "Explanation written by Claude from the items below, and checked before it was shown." : "Standard wording for this kind of cause."}</p>
      <h6>Evidence: ${plural(c.n_items, "outside item")}${agree}</h6>
      ${c.items.map(sourceItem).join("")}${more}
      ${reviewBox(c, i)}
    </li>`;
}

function setAside(data) {
  if (!data.set_aside.length) return "";
  const rows = data.set_aside.map((s) => `<li>${itemLink(s.item, "aside-title")}
      <span class="src-meta">${esc(s.item.source_label)} · ${esc(itemDates(s.item))}</span>
      <span class="aside-why"><b>Set aside:</b> ${esc(s.reason)}</span></li>`).join("");
  const extra = data.n_set_aside > data.set_aside.length ? ` The ${data.set_aside.length} most relevant of ${data.n_set_aside} are shown.` : "";
  return `<details class="drop" data-drop="aside"><summary><span class="caret" aria-hidden="true"></span>Looked at and set aside (${data.n_set_aside})</summary>
    <div class="drop-body"><p class="note">These are about the right kind of admission but failed one test, so they are not offered as a cause.${extra}</p>
    <ul class="aside">${rows}</ul></div></details>`;
}

export function causeView(data, name = savedName()) {
  if (data.error) return `<section class="d-block"><p class="loading">The outside sources could not be read: ${esc(data.error)}</p></section>`;
  const n = data.causes.length;
  const lead = n
    ? `<p class="d-text"><strong>${plural(n, "possible cause")}</strong> found in outside sources, best fit first.</p>
       <p class="d-text">These are suggestions for a person to check, not conclusions. Open each item to read the evidence, then confirm or reject it.</p>`
    : `<div class="d-quiet none-found"><strong>No outside explanation found.</strong>
         <p>None of the ${int(data.n_items_read)} outside items fits this hotspot on place, timing and diagnosis. That does not mean nothing is behind it. It may be a chance rise, or have a cause that no outside source reports. It needs a person to look.</p></div>`;
  const who = n ? `<div class="rv-name"><label for="rv-name">Your name, recorded with each decision</label>
      <input class="rv-input" id="rv-name" data-reviewer type="text" maxlength="60" value="${esc(name)}" placeholder="For example, J. Gutstein"></div>` : "";
  const list = n ? `<section class="d-block"><h4>Possible causes</h4><ol class="causes">${data.causes.map(causeCard).join("")}</ol></section>` : "";
  return `<section class="d-block">${lead}${who}</section>
    ${list}
    <section class="d-block"><h4>How this was worked out</h4>
      <p class="d-text">${int(data.n_items_read)} outside items were checked against this hotspot on three tests: is it about the <b>same place</b>, did it begin <b>before or with the rise</b> (taken to start on ${esc(longDate(data.rise_started))}), and is it about the <b>same kind of admission</b>. Only items that pass all three are offered.</p>
      <p class="d-source">${esc(data.note)}</p></section>
    <div class="drops">${setAside(data)}</div>
    <p class="d-hint">Every outside item is invented for this prototype, and each opens as its own page. In a real version these would be links to the sources' own websites. Detection does not use them. <a class="src-all" href="/external/" target="_blank" rel="noopener">Browse all outside items${NEW_TAB}</a></p>`;
}
