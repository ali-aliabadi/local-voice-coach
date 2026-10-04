// Every session you have done, and any one of them replayed in full.

import { moved } from "../chart.js";
import { escape, get, post } from "../form.js";
import * as notes from "../notes.js";
import * as draw from "../render.js";

const when = (stamp) => (stamp || "").slice(0, 16).replace("T", " ");

/** "34 min of a 30 min goal": how long it ran, against what you set out to do. */
const length = (s) => {
  if (s.minutes == null) return "";
  const ran = `${Math.max(1, Math.round(s.minutes))} min`;
  return s.goal_minutes ? `${ran} of a ${s.goal_minutes} min goal` : ran;
};

const PAGE = 50;   // matches history.PAGE: a full page means there may be more

const row = (s) => `
  <a class="pick" href="/history/${s.id}">
    <b>${escape(s.mode)} <span class="tag">${when(s.started_at)}</span></b>
    <span class="cost">${length(s)} · ${s.answers} answer${s.answers === 1 ? "" : "s"}</span>
    <span class="meta">${s.wpm == null ? "not scored" : `${Math.round(s.wpm)} wpm ·
      ${s.fillers.toFixed(1)} fillers per 100 words · ${s.pauses.toFixed(1)} pauses
      a minute · ${s.lead_in.toFixed(1)}s before speaking`}</span>
  </a>`;

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
      <p class="foot lead">Newest first. Open one to read the whole conversation back, with
      your own recordings.</p>
      <div class="table" id="sessions">${sessions.map(row).join("")}</div>
      <button class="link more" id="older" ${sessions.length < PAGE ? "hidden" : ""}>
        show older sessions</button>`;

    let oldest = sessions[sessions.length - 1].id;
    root.querySelector("#older").addEventListener("click", async (event) => {
      const more = await get(`/api/sessions?before=${oldest}`);
      root.querySelector("#sessions").insertAdjacentHTML("beforeend", more.map(row).join(""));
      if (more.length) oldest = more[more.length - 1].id;
      event.target.hidden = more.length < PAGE;
    });
  },
};

/** How much of the session was you talking: the partner should not be doing most of it. */
function spoke(session) {
  const mine = session.averages?.spoken;
  if (!mine || !session.minutes) return "";
  const share = Math.min(100, Math.round((mine / session.minutes) * 100));
  return ` · you spoke for ${mine < 1 ? "under a minute" : `${Math.round(mine)} min`} (${share}%)`;
}

/** Where the wait went after you stopped talking, averaged over the session's replies. */
function waits(turns) {
  const timed = turns.map((t) => t.timing).filter((t) => t?.total);
  if (!timed.length) return "";
  const mean = (key) => timed.reduce((sum, t) => sum + (t[key] || 0), 0) / timed.length / 1000;
  return `<p class="foot">Replies started ${mean("total").toFixed(1)}s after you stopped, on
    average: ${mean("hearing").toFixed(1)}s hearing you, ${mean("thinking").toFixed(1)}s thinking,
    ${mean("voicing").toFixed(1)}s voicing.</p>`;
}

/** How often you needed help to follow the partner: the listening half of the practice. */
function heard(l) {
  if (!l?.replies) return "";
  return `<p class="foot">You followed ${l.replies - l.helped} of ${l.replies} replies by ear
    alone${l.helped ? `; for ${l.helped} you heard it again, slower, or read the text` : ""}.</p>`;
}

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
      ${notes.answer(turn.notes)}
    </article>`;
}

/** Where the coach's summary goes: the summary, a "still writing" line, or a way to ask. */
function coaching(session) {
  if (session.coaching === "pending") {
    const done = session.turns.filter((t) => t.role === "you" && t.notes).length;
    return `<p class="callout">The coach is still writing: ${done} of ${session.answers}
      answers have notes so far. This page fills in by itself.</p>`;
  }
  const failed = session.coach_error
    ? `<p class="notice">The coach could not finish: ${escape(session.coach_error)}</p>` : "";
  if (session.summary) {
    const take = session.sheet
      ? `<p class="callout"><a href="/api/sessions/${session.id}/sheet.pdf" target="_blank">
          Open your study sheet (PDF)</a> — the fixes worth the most, phrases for your
          conversations, and what to practise tomorrow.</p>`
      : session.can_sheet
        ? `<p class="foot"><button class="link" id="sheet-now">Write your study sheet</button>
            — a page or two to keep, as a PDF.</p>` : "";
    return `<h2>Coach</h2>${failed}${take}${notes.summary(session.summary)}`;
  }
  if (!session.answers) return "";
  return failed + (session.coaching === "off"
    ? `<p class="foot">The coach is off. Choose a coach model in <a href="/settings">settings</a>
       to get notes on grammar, word choice and phrases for every answer.</p>`
    : `<p class="foot"><button class="link" id="coach-now">Write coach notes for this
       session</button> — grammar, word choice and phrases for each answer.</p>`);
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
      <p class="foot">${session.answers} answers · ${length(session)}${spoke(session)}
        · ${escape(session.model)}</p>
      ${heard(session.listening)}
      ${waits(session.turns)}
      ${changed(session.averages, session.previous)}
      ${session.answers ? '<div class="metrics" id="session-average"></div>' : ""}
      ${coaching(session)}
      <h2>The conversation</h2>
      ${expired ? `<p class="foot">Recordings from this session have expired — they are
        deleted after the retention window in <a href="/settings">settings</a>.</p>` : ""}
      ${(() => { let n = 0; return session.turns.map((turn) => {
        if (turn.role === "you") return answerBlock(turn, ++n);
        if (turn.role === "review") {
          return `<article class="turn critique">${escape(turn.text)}</article>`;
        }
        const who = turn.role.startsWith("panel:") ? turn.role.slice(6) : session.partner;
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

    const again = () => setTimeout(() => {
      // Only while this page is still the one showing: navigating away ends the polling.
      if (location.pathname === `/history/${params.id}`) detail.render(root, params);
    }, 4000);
    root.querySelector("#coach-now")?.addEventListener("click", async () => {
      await post(`/api/sessions/${params.id}/coach`, {});
      again();
    });
    root.querySelector("#sheet-now")?.addEventListener("click", async (event) => {
      event.target.textContent = "Writing your study sheet…";
      await post(`/api/sessions/${params.id}/sheet`, {});
      again();
    });
    if (session.coaching === "pending") again();
  },
};
