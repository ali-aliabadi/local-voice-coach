// Everything, across every session. The point of the whole exercise is watching these
// four numbers move.

import { get } from "../form.js";
import * as render_ from "../render.js";

const CARDS = [
  ["sessions", "sessions"],
  ["answers", "answers given"],
  ["words", "words spoken"],
];

export async function render(root) {
  const { totals, trend } = await get("/api/progress");
  if (!totals.answers) {
    root.innerHTML = `<h1>Progress</h1>
      <p class="foot">Nothing yet. <a href="/modes">Practise once</a> and this fills in.</p>`;
    return;
  }

  root.innerHTML = `
    <h1>Progress</h1>
    <div class="metrics">
      ${CARDS.map(([key, label]) =>
        `<div class="metric"><b>${Math.round(totals[key] || 0).toLocaleString()}</b>
         <span>${label}</span></div>`).join("")}
    </div>
    <h2>Across every session</h2>
    <div class="metrics">
      <div class="metric"><b>${Math.round(totals.wpm)}</b><span>words / min</span></div>
      <div class="metric"><b>${totals.fillers.toFixed(1)}</b><span>fillers per answer</span></div>
      <div class="metric"><b>${totals.pauses.toFixed(1)}</b><span>pauses per answer</span></div>
      <div class="metric"><b>${totals.lead_in.toFixed(1)}s</b><span>before speaking</span></div>
    </div>
    <h2>Over time</h2>
    <div id="trend"></div>
    <p class="foot">Words per minute going up is good. Fillers, pauses and the silence
    before you start going down is the whole point.</p>`;

  render_.trend(root.querySelector("#trend"), trend);
}
