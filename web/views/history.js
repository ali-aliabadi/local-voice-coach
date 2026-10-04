// Every session you have done, and any one of them replayed in full.

import { moved } from "../chart.js";
import { escape, get } from "../form.js";
import * as draw from "../render.js";

const when = (stamp) => (stamp || "").slice(0, 16).replace("T", " ");

export const list = {
  async render(root) {
    root.innerHTML = `<h1>History</h1><p class="foot loading">Loading…</p>`;
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
            <span class="meta">${s.wpm == null ? "not scored" : `${Math.round(s.wpm)} wpm ·
              ${s.fillers.toFixed(1)} fillers per 100 words · ${s.pauses.toFixed(1)} pauses
              a minute · ${s.lead_in.toFixed(1)}s before speaking`}</span>
          </a>`).join("")}
      </div>`;
  },
};

/** The sentence a trainer opens with. Only mentions what actually moved. */
function changed(now, before) {
  if (!before || !Object.keys(before).length) return "";
  const shifts = Object.keys(now).map((key) => moved(key, now[key], before[key])).filter(Boolean);
  if (!shifts.length) return `<p class="callout">About the same as your last session.</p>`;

  const good = shifts.filter((s) => s.better).map((s) => s.text);
  const bad = shifts.filter((s) => !s.better).map((s) => s.text);
  const parts = [];
  if (good.length) parts.push(`<b>${good.join(", ")}</b> than last time`);
  if (bad.length) parts.push(`${good.length ? "but " : ""}${bad.join(", ")}`);
  return `<p class="callout">${parts.join(" — ")}</p>`;
}

function answerBlock(turn, index) {
  return `
    <article class="turn you">
      <span class="who mine">Your answer ${index}</span>
      <div class="metrics" data-metrics="${turn.id}"></div>
      <div data-timeline="${turn.id}"></div>
      <p class="transcript" data-transcript="${turn.id}"></p>
      ${turn.has_audio
        ? `<audio controls preload="none" src="/api/audio/${turn.id}"></audio>` : ""}
    </article>`;
}

export const detail = {
  async render(root, params) {
    root.innerHTML = `<p class="foot loading">Loading…</p>`;
    const session = await get(`/api/sessions/${params.id}`);
    if (session.error) {
      root.innerHTML = `<h1>Not found</h1><p class="foot">
        <a href="/history">Back to history</a></p>`;
      return;
    }
    const answers = session.turns.filter((t) => t.role === "you");
    const expired = answers.length && answers.every((t) => !t.has_audio);

    root.innerHTML = `
      <p class="crumbs"><a href="/history">history</a> › <b>${escape(session.mode)}</b></p>
      <h1>${when(session.started_at)}</h1>
      <p class="foot">${session.answers} answers · ${escape(session.model)}</p>
      ${changed(session.averages, session.previous)}
      ${session.answers ? '<div class="metrics" id="session-average"></div>' : ""}
      <h2>The conversation</h2>
      ${expired ? `<p class="foot">Recordings from this session have expired — they are
        deleted after the retention window in <a href="/settings">settings</a>.</p>` : ""}
      ${(() => { let n = 0; return session.turns.map((turn) => {
        if (turn.role === "you") return answerBlock(turn, ++n);
        if (turn.role === "review") {
          return `<article class="turn critique">${escape(turn.text)}</article>`;
        }
        const who = turn.role.startsWith("panel:") ? turn.role.slice(6) : "Interviewer";
        return `<article class="turn them"><span class="who">${escape(who)}</span>
          ${escape(turn.text)}</article>`;
      }).join(""); })()}`;

    if (session.answers) {
      draw.metrics(root.querySelector("#session-average"), session.averages, session.lifetime);
    }
    // The per-word data was stored with the answer, so a session from weeks ago still
    // shows its highlighted fillers and its pauses, not just the totals.
    for (const turn of answers) {
      if (turn.wpm !== null) draw.metrics(root.querySelector(`[data-metrics="${turn.id}"]`), turn);
      draw.timeline(root.querySelector(`[data-timeline="${turn.id}"]`), turn.word_rows);
      draw.transcript(
        root.querySelector(`[data-transcript="${turn.id}"]`), turn.word_rows, turn.text);
    }
  },
};
