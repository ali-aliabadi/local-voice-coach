// Everything, across every session. Watching these four numbers move is the point.

import * as chart from "../chart.js";
import { get } from "../form.js";
import { repeats } from "../notes.js";
import { metrics } from "../render.js";

const COUNTS = [
  ["sessions", "sessions"],
  ["answers", "answers given"],
  ["words", "words spoken"],
];

export async function render(root) {
  root.innerHTML = `<h1>Progress</h1><p class="foot loading">Reading your sessions…</p>`;
  const { totals, trend, mistakes } = await get("/api/progress");

  if (!totals.answers) {
    root.innerHTML = `<h1>Progress</h1>
      <p class="foot">Nothing yet. <a href="/modes">Practise once</a> and this fills in.</p>`;
    return;
  }

  root.innerHTML = `
    <h1>Progress</h1>
    <div class="counts">
      ${COUNTS.map(([key, label]) =>
        `<div class="count"><b>${Math.round(totals[key] || 0).toLocaleString()}</b>
         <span>${label}</span></div>`).join("")}
    </div>
    <h2>Where you are now</h2>
    <p class="foot lead">Averaged across every answer you have ever given.</p>
    <div class="metrics" id="lifetime"></div>
    ${mistakes.length ? `<h2>Mistakes you repeat</h2>
      <p class="foot lead">What the coach corrected most over the last 7 days. The patterns,
      not the one-off slips, are what is worth practising.</p>${repeats(mistakes)}` : ""}
    <h2>How it has moved</h2>
    <div id="trend"></div>`;

  metrics(root.querySelector("#lifetime"), totals);
  chart.trend(root.querySelector("#trend"), trend);
}
