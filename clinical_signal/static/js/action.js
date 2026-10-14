// The "Who can act" tab: part three.
// For each cause a person confirmed on the second tab, it names the business area that owns
// it and that area's standard recommendation. Both come from one mapping file by fixed rules.
// A person then accepts, edits, or declines; on accept a hand-off message is shown to copy
// and send (the app sends nothing), and the owner's answer is recorded.
// With no confirmed cause there is no recommendation, only "Needs analyst review".

import { esc, int, longDate, plural } from "./format.js";
import { savedName } from "./cause.js";

const when = (iso) => {
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })} at ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
};
const NEW_TAB = `<span class="src-new" aria-hidden="true">&#8599;</span><span class="sr"> (opens in a new tab)</span>`;
const team = (owner) => owner.split(",")[0];

function mappingNote(mapping) {
  if (!mapping || !mapping.entries) return `<p class="d-quiet">No mapping file is loaded, so this tab can only say “Needs analyst review”.</p>`;
  const rows = mapping.owners.map((o) => `<div><dt>${esc(o.owner)}</dt><dd>${plural(o.count, "entry", "entries")}</dd></div>`).join("");
  const drafts = mapping.entries - mapping.approved;
  return `<dl class="facts">${rows}</dl>
    <p class="d-hint">${int(mapping.entries)} entries covering ${int(mapping.kinds_of_cause)} kinds of cause. ${drafts ? `${drafts === mapping.entries ? "All" : int(drafts)} are drafts written for this prototype: no business area has approved them yet.` : "All are approved."}</p>`;
}

export function actionIntro(meta, pick) {
  return `<section class="d-block"><p class="d-text"><strong>${esc(pick)}</strong></p>
      <p class="d-text">Once a person has confirmed what is driving a hotspot, this tab names the team that can do something about it and what that team would normally do.</p></section>
    <section class="d-block"><h4>Where the recommendations come from</h4>
      <p class="d-text">One mapping file lists, for each kind of cause, the business area that owns it and that area’s standard recommendation. In a real plan each area would write and approve its own entries.</p>
      ${mappingNote(meta && meta.mapping)}</section>
    <section class="d-block"><h4>Who decides what</h4>
      <ul class="plain"><li><b>Fixed rules</b> pick the owner and the recommendation from the mapping. The same cause always gives the same answer.</li>
      <li><b>AI</b> rewords a recommended action for the hotspot and drafts the hand-off message. It cannot change the owner or the action.</li>
      <li><b>The analyst</b> accepts, edits, or declines, and sends the message themselves. This app sends nothing.</li>
      <li><b>The owning team</b> says whether it is the right action. Their answer is recorded here.</li></ul></section>`;
}

export const actionLoading = () => `<div data-actions><section class="d-block"><p class="loading">Looking up who can act…</p></section></div>`;

function chain(h, r) {
  const c = r.cause;
  const items = c.items.map((i) => `<li><a class="src-title" href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.title)}${NEW_TAB}</a></li>`).join("");
  const std = r.written_by === "claude" ? ` Standard wording: “${esc(r.standard)}”` : "";
  const why = r.outcome === "unmapped" ? "The mapping has no entry for this kind of cause."
    : `It is the standard recommendation for this kind of cause in the mapping, listed under ${esc(team(r.owner))}.${std}`;
  return `<ol class="chain">
      <li><b>The hotspot.</b> ${esc(h.title)}, ${esc(h.where)}: ${int(h.reported)} member admissions reported in the ${esc(h.period)}, against about ${int(h.expected)} expected.</li>
      <li><b>The confirmed cause.</b> ${esc(c.label)}. The evidence was rated ${esc(c.strength)}. Confirmed by ${esc(c.confirmed_by)} on ${esc(when(c.confirmed_at))}.${c.note ? ` Note: “${esc(c.note)}”` : ""}
        <ul class="chain-items">${items}</ul></li>
      <li><b>Why this recommendation.</b> ${why}</li>
      <li><b>Why this owner.</b> ${esc(r.why_owner)}</li>
    </ol>`;
}

const status = (mark, cls, html) => `<p class="rv-status ${cls}"><span class="rv-mark" aria-hidden="true">${mark}</span><span>${html}</span></p>`;

export function decisionBox(r, i) {
  const d = r.decision, t = esc(r.topic);
  if (r.stage === "to_decide") {
    return `<div class="ad" data-topic="${t}">
      ${status("&ndash;", "", `<b>Not decided yet.</b> Nothing goes to ${esc(team(r.owner))} until a person accepts it.`)}
      <label class="rv-note" for="ad-text-${i}">Recommendation (you can edit the wording before accepting)</label>
      <textarea class="rv-input ad-area" id="ad-text-${i}" data-act-text rows="4" maxlength="600">${esc(r.text)}</textarea>
      <label class="rv-note" for="ad-note-${i}">Note (optional)</label>
      <input class="rv-input" id="ad-note-${i}" data-act-note type="text" maxlength="500" placeholder="Why you decided this">
      <div class="rv-btns" role="group" aria-label="Your decision on the recommendation for: ${esc(r.cause.label)}">
        <button type="button" class="rv-btn" data-act="accepted">Accept</button>
        <button type="button" class="rv-btn" data-act="declined">Decline</button></div></div>`;
  }
  const note = d.note ? ` Note: “${esc(d.note)}”` : "";
  const undo = `<button type="button" class="rv-btn is-quiet" data-act="undo">Undo decision</button>`;
  if (r.stage === "declined") {
    return `<div class="ad" data-topic="${t}">
      ${status("&times;", "is-rejected", `<b>Declined</b> by ${esc(d.reviewer)} on ${esc(when(d.at))}. Nothing was handed off.${note}`)}
      <div class="rv-btns">${undo}</div></div>`;
  }
  const accepted = status("&#10003;", "is-confirmed", `<b>Accepted</b> by ${esc(d.reviewer)} on ${esc(when(d.at))}.${d.edited ? " The wording was edited." : ""}${note}`)
    + (d.edited ? `<p class="act-final"><b>As accepted:</b> ${esc(d.text)}</p>` : "");
  if (r.stage === "accepted") {
    const m = r.draft;
    return `<div class="ad" data-topic="${t}">${accepted}
      <h6>Hand-off message</h6>
      <p class="d-source">${r.draft_by === "claude" ? "Drafted by Claude from the facts above, and checked before it was shown." : "Standard message, filled in from the facts above."} Edit it, copy it into an email or chat, then mark it as handed off. This app does not send it.</p>
      <p class="ad-to"><b>To:</b> ${esc(m.to)}</p>
      <label class="rv-note" for="ho-subject-${i}">Subject</label>
      <input class="rv-input" id="ho-subject-${i}" data-ho-subject type="text" maxlength="200" value="${esc(m.subject)}">
      <label class="rv-note" for="ho-body-${i}">Message</label>
      <textarea class="rv-input ad-area" id="ho-body-${i}" data-ho-body rows="12" maxlength="2500">${esc(m.body)}</textarea>
      <div class="rv-btns"><button type="button" class="rv-btn" data-act="copy">Copy message</button>
        <button type="button" class="rv-btn" data-act="handoff">Mark as handed off</button>${undo}</div></div>`;
  }
  const h = d.handoff, a = d.answer;
  const answered = a
    ? status(a.answer === "agreed" ? "&#10003;" : "&times;", a.answer === "agreed" ? "is-confirmed" : "is-rejected",
      `<b>${esc(team(r.owner))} ${a.answer === "agreed" ? "agreed" : "said this is not the right action"}</b>, recorded on ${esc(when(a.at))}.${a.note ? ` Note: “${esc(a.note)}”` : ""}${a.answer === "declined" ? ` This goes back to ${esc(team(r.owner))} to revise its entry in the mapping.` : ""}`)
    : status("?", "", `<b>Waiting for ${esc(team(r.owner))} to answer.</b> Record what they say here.`);
  return `<div class="ad" data-topic="${t}">${accepted}
      ${status("&rarr;", "is-confirmed", `<b>Handed off</b> to ${esc(h.to)} on ${esc(when(h.at))}.`)}
      <details class="drop ad-sent"><summary><span class="caret" aria-hidden="true"></span>The message that was sent</summary>
        <div class="drop-body"><p class="ad-to"><b>Subject:</b> ${esc(h.subject)}</p><pre class="ad-pre">${esc(h.body)}</pre></div></details>
      <h6>The owner’s answer</h6>${answered}
      <label class="rv-note" for="ans-note-${i}">What they said (optional)</label>
      <input class="rv-input" id="ans-note-${i}" data-ans-note type="text" maxlength="500" value="${esc(a?.note || "")}" placeholder="For example, already under way">
      <div class="rv-btns" role="group" aria-label="The owner’s answer">
        <button type="button" class="rv-btn" data-act="agreed" aria-pressed="${a?.answer === "agreed"}">Owner agreed</button>
        <button type="button" class="rv-btn" data-act="owner-declined" aria-pressed="${a?.answer === "declined"}">Owner said no</button>
        <button type="button" class="rv-btn is-quiet" data-act="unhandoff">Undo hand-off</button></div>
      <p class="d-hint"><b>Closing the loop.</b> The next daily run will show here whether this hotspot is still flagged. It will not claim that the action caused any change.</p></div>`;
}

function card(h, r, i) {
  const draft = r.status && r.status.toLowerCase() !== "approved";
  const source = r.source ? `<p class="d-source">Background for this draft: <a class="src-all" href="${esc(r.source.url)}" target="_blank" rel="noopener">${esc(r.source.title)}${NEW_TAB}</a>. It shows this kind of action is established practice, not that it would work here.</p>` : "";
  const also = r.also_consider.length ? `<details class="drop"><summary><span class="caret" aria-hidden="true"></span>Also consider (${r.also_consider.length})</summary>
      <div class="drop-body"><ul class="plain">${r.also_consider.map((a) => `<li>${esc(a)}</li>`).join("")}</ul></div></details>` : "";
  const earlier = r.earlier ? `<p class="d-quiet"><b>Still flagged.</b> This was handed off to ${esc(r.earlier.to)} on the data for ${esc(longDate(r.earlier.as_of))}, ${plural(r.earlier.days, "day")} ago, and the hotspot is still here. That does not show whether the action was taken or whether it worked.</p>` : "";
  return `<li class="cause act is-${esc(r.outcome)}">
      <div class="cause-head"><span class="cause-rank" aria-hidden="true">${i + 1}</span><h5><span class="sr">Recommendation ${i + 1}: </span>${esc(r.outcome_label)}</h5></div>
      <p class="act-for">For the confirmed cause: <b>${esc(r.cause.label)}</b></p>
      <dl class="facts"><div><dt>Owner</dt><dd>${esc(r.owner)}</dd></div><div><dt>Point of contact</dt><dd>${esc(r.contact_role)}</dd></div></dl>
      <p class="d-text act-text">${esc(r.text)}</p>
      <p class="d-source">${r.written_by === "claude" ? "Reworded for this hotspot by Claude, and checked before it was shown." : "Standard wording from the mapping."}${draft ? ` <span class="act-draft">Draft</span> ${esc(team(r.owner))} has not approved this entry yet.` : ""}</p>
      ${source}
      ${r.caution ? `<p class="d-quiet"><b>Caution.</b> ${esc(r.caution)}</p>` : ""}${earlier}
      <h6>How we got here</h6>${chain(h, r)}
      ${also}
      ${decisionBox(r, i)}
    </li>`;
}

export function actionView(data, name = savedName()) {
  if (data.error) return `<section class="d-block"><p class="loading">Who can act could not be worked out: ${esc(data.error)}</p></section>`;
  if (data.default) {
    const d = data.default;
    return `<section class="d-block"><div class="d-quiet none-found"><strong>Needs analyst review</strong>
        <p>${esc(d.text)}</p></div>
      <dl class="facts act-default"><div><dt>Who has it for now</dt><dd>${esc(d.owner)}</dd></div></dl>
      <p class="d-hint">This is a next step, not a recommendation. A recommendation is only made for a cause a person has confirmed, so nobody is asked to act on a guess.</p></section>`;
  }
  const n = data.recommendations.length;
  const notes = [...new Set(data.recommendations.map((r) => r.ai_note))].map((t) => `<p class="d-source">${esc(t)}</p>`).join("");
  return `<section class="d-block"><p class="d-text"><strong>${plural(n, "recommendation")}</strong>, one for each cause a person confirmed.</p>
      <p class="d-text">Each names the team that can act and what that team would normally do. Nothing is sent to anyone until you accept it and send the message yourself.</p>
      <div class="rv-name"><label for="ad-name">Your name, recorded with each decision</label>
      <input class="rv-input" id="ad-name" data-act-reviewer type="text" maxlength="60" value="${esc(name)}" placeholder="For example, J. Gutstein"></div></section>
    <section class="d-block"><h4>Recommendations</h4><ol class="causes">${data.recommendations.map((r, i) => card(data.hotspot, r, i)).join("")}</ol></section>
    <section class="d-block"><h4>How this was worked out</h4>
      <p class="d-text">Fixed rules looked up each confirmed cause in the mapping file, which gives the owner and the recommendation. The estimate of extra admissions and cost is on the Detected tab; no new estimate is made here.</p>
      ${notes}</section>
    <p class="d-hint">Every entry in the mapping is a draft written for this prototype. The teams and roles are real kinds of team at a health plan; no real person is named or contacted.</p>`;
}
