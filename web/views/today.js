// Home: where you stand today, and one tap to carry on. A daily habit should not start
// with two menus.

import { lastGoal } from "../clock.js";
import { escape, get } from "../form.js";
import { go } from "../router.js";

const LAST = "coach.last";

/** The mode and model you used last, so tomorrow starts where today left off. */
export function keepLast(mode, backend) {
  try { localStorage.setItem(LAST, JSON.stringify({ mode, backend })); } catch { /* fine */ }
}
/** Telegram in words: off, on, or what Relay's check at the start found wrong. The header
 * says it on every page; the Today page says it in full. */
export const telegram = (w) => (w.telegram.length
  ? { word: "off", detail: `.env needs ${w.telegram.join(", ")}` }
  : w.problem ? { word: "not working", detail: w.problem }
  : { word: "on", detail: `sends to ${w.to}` });

const last = () => { try { return JSON.parse(localStorage.getItem(LAST) || "null"); } catch { return null; } };

export async function render(root) {
  root.innerHTML = `<h1>Today</h1><p class="foot loading">Loading…</p>`;
  const t = await get("/api/today");
  const goal = lastGoal();
  const done = Math.round(t.minutes);
  const usual = last();
  const share = goal ? Math.min(100, (t.minutes / goal) * 100) : 0;
  const relay = telegram(t.wired);

  root.innerHTML = `
    <h1>Today</h1>
    <div class="counts">
      <div class="count"><b>${done}</b><span>minutes practised${goal ? ` of ${goal}` : ""}</span></div>
      <div class="count"><b>${t.streak}</b><span>day${t.streak === 1 ? "" : "s"} in a row</span></div>
      <div class="count"><b>${Math.round(t.spoken)}</b><span>minutes of you speaking</span></div>
    </div>
    ${goal ? `<div class="goalbar today-bar"><i style="width:${share}%"></i></div>` : ""}
    <p class="foot lead">${goal && t.minutes >= goal ? "Goal reached for today. Anything more is extra."
      : t.sessions ? "Good start. Keep going while it is fresh." : "Nothing yet today."}</p>
    <div class="row start">
      ${usual ? `<button class="primary" id="go">Continue: ${escape(usual.mode)}</button>` : ""}
      <a href="/modes">${usual ? "or choose something else" : "Choose what to practise"}</a>
    </div>
    <p class="foot wired">Gemini: ${t.wired.gemini ? "key set"
      : `no key — <a href="/settings">add one</a>`} · Telegram: ${relay.word} —
      ${escape(relay.detail)}</p>
    ${t.work_on.length ? `<h2>From your last session, work on</h2>
      <ol class="advice">${t.work_on.map((w) => `<li>${escape(w)}</li>`).join("")}</ol>` : ""}
    ${t.phrases.length ? `<h2>Phrases to try out today</h2>
      <dl class="phrases">${t.phrases.map((p) => `<dt>${escape(p.phrase)}</dt>
        <dd>${escape(p.meaning)}</dd>`).join("")}</dl>` : ""}`;

  root.querySelector("#go")?.addEventListener("click", () =>
    go(`/practice?mode=${usual.mode}&backend=${usual.backend}&goal=${goal}`));
}
