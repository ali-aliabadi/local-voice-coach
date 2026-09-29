// Every session you have done, and any one of them replayed in full.

import { escape, get } from "../form.js";
import * as draw from "../render.js";

const when = (stamp) => (stamp || "").slice(0, 16).replace("T", " ");

export const list = {
  async render(root) {
    const sessions = await get("/api/sessions");
    if (!sessions.length) {
      root.innerHTML = `<h1>History</h1>
        <p class="foot">No sessions yet. <a href="/modes">Practise once</a> and they
        show up here.</p>`;
      return;
    }
    root.innerHTML = `
      <h1>History</h1>
      <p class="foot lead">${sessions.length} session${sessions.length === 1 ? "" : "s"}.
      Open one to read the whole conversation back, with your own recordings.</p>
      <div class="table">
        ${sessions.map((s) => `
          <a class="pick" href="/history/${s.id}">
            <b>${escape(s.mode)} <span class="tag">${when(s.started_at)}</span></b>
            <span class="cost">${s.answers} answer${s.answers === 1 ? "" : "s"}</span>
            <span class="meta">${Math.round(s.wpm)} wpm ·
              ${s.fillers.toFixed(1)} fillers · ${s.pauses.toFixed(1)} pauses ·
              ${s.lead_in.toFixed(1)}s before speaking</span>
          </a>`).join("")}
      </div>`;
  },
};

function answerBlock(turn) {
  return `
    <article class="turn you">
      <div class="metrics" data-metrics="${turn.id}"></div>
      <div data-timeline="${turn.id}"></div>
      <p class="transcript" data-transcript="${turn.id}"></p>
      ${turn.has_audio
        ? `<audio controls preload="none" src="/api/audio/${turn.id}"></audio>`
        : `<p class="foot">Recording has expired — they are deleted after the retention
           window in settings.</p>`}
    </article>`;
}

export const detail = {
  async render(root, params) {
    const session = await get(`/api/sessions/${params.id}`);
    if (session.error) {
      root.innerHTML = `<h1>Not found</h1><p class="foot">
        <a href="/history">Back to history</a></p>`;
      return;
    }
    const avg = session.averages;

    root.innerHTML = `
      <p class="crumbs"><a href="/history">history</a> › <b>${escape(session.mode)}</b></p>
      <h1>${when(session.started_at)}</h1>
      <p class="foot">${session.answers} answers · ${escape(session.model)}</p>
      ${session.answers ? `<div class="metrics">
        <div class="metric"><b>${Math.round(avg.wpm)}</b><span>words / min</span></div>
        <div class="metric"><b>${avg.fillers.toFixed(1)}</b><span>fillers per answer</span></div>
        <div class="metric"><b>${avg.pauses.toFixed(1)}</b><span>pauses per answer</span></div>
        <div class="metric"><b>${avg.lead_in.toFixed(1)}s</b><span>before speaking</span></div>
      </div>` : ""}
      <h2>The conversation</h2>
      ${session.turns.map((turn) => {
        if (turn.role === "you") return answerBlock(turn);
        if (turn.role === "review") {
          return `<article class="turn critique">${escape(turn.text)}</article>`;
        }
        const who = turn.role.startsWith("panel:") ? turn.role.slice(6) : "Interviewer";
        return `<article class="turn them"><span class="who">${escape(who)}</span>
          ${escape(turn.text)}</article>`;
      }).join("")}`;

    // The per-word data was stored with the answer, so a session from weeks ago still
    // shows its highlighted fillers and its pauses, not just the totals.
    for (const turn of session.turns.filter((t) => t.role === "you")) {
      const metrics = root.querySelector(`[data-metrics="${turn.id}"]`);
      if (turn.wpm !== null) draw.metrics(metrics, turn);
      draw.timeline(root.querySelector(`[data-timeline="${turn.id}"]`), turn.word_rows);
      draw.transcript(
        root.querySelector(`[data-transcript="${turn.id}"]`), turn.word_rows, turn.text);
    }
  },
};
