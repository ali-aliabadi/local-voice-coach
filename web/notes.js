// The coach's writing: a summary for the session, notes on each answer. Read after the
// session, never during it. Models do not always return the shape asked for, so every
// field is optional and a plain-text reply is shown as it came.

import { escape } from "./form.js";

const list = (items, tag = "ul") => (items?.length
  ? `<${tag}>${items.map((i) => `<li>${escape(i)}</li>`).join("")}</${tag}>` : "");

const phrases = (items) => (items?.length
  ? `<dl class="phrases">${items.map((p) => `<dt>${escape(p.phrase)}</dt>
      <dd>${escape(p.meaning)}</dd>`).join("")}</dl>` : "");

export function summary(s) {
  if (!s) return "";
  if (s.text) return `<section class="coach"><p>${escape(s.text)}</p></section>`;
  return `<section class="coach">
    ${s.went_well ? `<p class="good-news">${escape(s.went_well)}</p>` : ""}
    ${s.work_on?.length ? `<h3>Work on next</h3>${list(s.work_on, "ol")}` : ""}
    ${s.phrases?.length ? `<h3>Phrases worth learning</h3>${phrases(s.phrases)}` : ""}
    ${s.instead_of_um?.length
      ? `<h3>Instead of "um", try</h3>${list(s.instead_of_um)}` : ""}
  </section>`;
}

export function answer(n) {
  if (!n) return "";
  if (n.text) return `<div class="notes"><p>${escape(n.text)}</p></div>`;
  const fixes = (n.fixes || []).map((f) => `<li>
      <span class="said">${escape(f.said)}</span> → <b>${escape(f.better)}</b>
      ${f.why ? `<span class="why">${escape(f.why)}</span>` : ""}</li>`).join("");
  return `<div class="notes">
    ${n.praise ? `<p class="good-news">${escape(n.praise)}</p>` : ""}
    ${fixes ? `<ul class="fixes">${fixes}</ul>` : '<p class="foot">Nothing worth fixing.</p>'}
    ${n.natural ? `<p class="natural"><span>A native speaker might say:</span>
      ${escape(n.natural)}</p>` : ""}
    ${phrases(n.phrases)}
  </div>`;
}

/** "articles — 9 times": the fixes the coach keeps making, so the pattern is visible. */
export function repeats(counts) {
  if (!counts?.length) return "";
  return `<ul class="repeats">${counts.slice(0, 6).map(([kind, n]) =>
    `<li><b>${escape(kind)}</b> <span>${n} time${n === 1 ? "" : "s"}</span></li>`).join("")}
  </ul>`;
}
