// An interview's verdict, the way a real interviewer submits it: a rating out of 10, the
// decision on its whole scale - so "Yes" reads as the middle of five, not a pass - a score
// for each area, and the evidence. Telegram only gets the headline; all of it is here.

import { escape } from "./form.js";

export const DECISIONS = ["No", "Not sure", "Yes", "Definitely hire", "They could have my job"];

const list = (title, items) => (items?.length
  ? `<h3>${title}</h3><ul>${items.map((item) => `<li>${escape(item)}</li>`).join("")}</ul>`
  : "");

/** The verdict in full. */
export function card(v) {
  const scale = DECISIONS.map((d) => (d === v.decision
    ? `<li aria-current="true">${escape(d)}</li>` : `<li>${escape(d)}</li>`)).join("");
  const areas = Object.entries(v.scores || {}).map(([area, score]) => `
    <div class="area"><span>${escape(area)}</span><b>${Number(score)}</b>
      <i class="track" aria-hidden="true"><i style="width: ${Number(score) * 10}%"></i></i>
    </div>`).join("");
  const votes = (v.votes || []).map((vote) => `<li><b>${escape(vote.name)}</b>:
    ${escape(vote.decision)} — ${escape(vote.why)}</li>`).join("");
  return `<section class="hiring">
    <h2>The interviewer's verdict</h2>
    <p class="rating"><b>${Number(v.rating)}</b><span>/10</span>
      ${v.level ? `<span class="level">came across as ${escape(v.level)}</span>` : ""}</p>
    <ol class="decisions" aria-label="Would they hire you?">${scale}</ol>
    ${v.summary ? `<p>${escape(v.summary)}</p>` : ""}
    ${areas ? `<div class="areas">${areas}</div>` : ""}
    ${list("What held up", v.strengths)}
    ${list("What worried them", v.concerns)}
    ${v.would_change ? `<h3>What would have changed it</h3><p>${escape(v.would_change)}</p>` : ""}
    ${votes ? `<h3>Each interviewer's vote</h3><ul>${votes}</ul>` : ""}
  </section>`;
}

/** Where the verdict goes on a session page: the verdict, or a way to ask for it. */
export function section(s) {
  if (s.verdict) return card(s.verdict);
  if (!s.interview || !s.counted || s.coaching === "pending") return "";
  return s.can_verdict
    ? `<p class="foot"><button class="link" id="verdict-now">Write the interviewer's
        verdict</button> — a rating out of 10, and whether they would hire you.</p>`
    : `<p class="foot">Choose an interview verdict model in <a href="/settings">settings</a>
        to hear whether they would hire you.</p>`;
}
