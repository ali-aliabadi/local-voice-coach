// What the practice page shows. practice.js decides what happens; this draws it.

import { escape } from "./form.js";
import * as draw from "./render.js";

let root = null;
let ticking = null;    // the seconds counter while you wait on something
const SHOW = "coach.showText";
let showText = (() => { try { return localStorage.getItem(SHOW) === "1"; } catch { return false; } })();

export const $ = (sel) => root.querySelector(sel);

export function mount(node) {
  root = node;
  root.innerHTML = `
    <div class="topline"><p class="status" id="status"></p><p class="clock" id="clock"></p></div>
    <div class="goalbar" aria-hidden="true"><i id="goalfill"></i></div>
    <p class="scene" id="scene" hidden></p>
    <p class="question" id="question">Connecting…</p>
    <p class="listen-tools" id="listen-tools" hidden>
      <button class="link" id="again">again</button> ·
      <button class="link" id="slower">slower</button> ·
      <button class="link" id="reveal">show text</button>
    </p>
    <div class="stage">
      <button id="mic" class="mic" disabled aria-label="Answer" aria-pressed="false"></button>
      <p class="mic-label" id="mic-label">connecting</p>
      <canvas id="level" width="240" height="28" aria-hidden="true"></canvas>
      <p class="hint">space bar works too · answer out loud, as if it were real</p>
      <p class="notice" id="notice" role="alert" hidden></p>
    </div>
    <section id="card" class="card-result" aria-live="polite" hidden></section>
    <section id="session" class="session" hidden>
      <h2>This session</h2>
      <div class="metrics" id="session-metrics"></div>
    </section>
    <section id="result" aria-live="polite" hidden>
      <h2>Your last answer</h2>
      <div class="metrics" id="metrics"></div>
      <div id="timeline"></div>
      <p class="transcript" id="transcript"></p>
      <div class="row">
        <audio id="replay" controls preload="none"></audio>
        <span class="hint">hearing your own hesitation teaches faster than the number</span>
      </div>
      <article id="critique" class="critique" hidden></article>
    </section>
    <button class="link end" id="end">end session and review it</button>`;
  $("#reveal").addEventListener("click", () => {
    showText = !showText;
    try { localStorage.setItem(SHOW, showText ? "1" : "0"); } catch { /* convenience */ }
    veil();
  });
}

/** Whether you can read the partner's words right now: reading counts as help. */
export const reading = () => $("#question").dataset.spoken === "1" && showText;

export function mic(enabled, label) {
  clearInterval(ticking);
  $("#mic").disabled = !enabled;
  $("#mic-label").textContent = label;
}

/** Disabled, with a seconds counter: a silent wait should never look like nothing. */
export function wait(label) {
  mic(false, `${label}…`);
  const since = Date.now();
  ticking = setInterval(() => {
    const seconds = Math.round((Date.now() - since) / 1000);
    if (seconds >= 3) $("#mic-label").textContent = `${label}… ${seconds}s`;
  }, 1000);
}

/** The line where the partner's words go: either their words, or a status like "Connecting". */
export function say(text, spoken) {
  $("#question").textContent = text;
  $("#question").dataset.spoken = spoken ? "1" : "";
  veil();
}

/** Blur what the partner said until asked: hearing it is the exercise. */
function veil() {
  const spoken = $("#question").dataset.spoken === "1";
  $("#question").classList.toggle("veiled", spoken && !showText);
  $("#listen-tools").hidden = !spoken;
  $("#reveal").textContent = showText ? "hide text" : "show text";
}

/** A message beside the mic. `retry` adds a button that calls it; `good` is not a warning. */
export function notice(text, { retry = null, good = false } = {}) {
  const box = $("#notice");
  box.hidden = false;
  box.classList.toggle("good", good);
  box.innerHTML = escape(text) + (retry ? '<button id="retry">Try again</button>' : "");
  box.querySelector("#retry")?.addEventListener("click", () => {
    box.hidden = true;
    retry();
  });
}

export function status(answered, detail) {
  $("#status").textContent =
    `${answered === 0 ? "no answers yet" : `${answered} answered`}  ·  ${detail}`;
}

/** Clear the last answer's details: a new turn is starting. */
export function reset() {
  $("#result").hidden = true;
  $("#critique").hidden = true;
  $("#notice").hidden = true;
}

export function answer(event, lifetime) {
  $("#result").hidden = false;
  if (event.metrics) draw.metrics($("#metrics"), event.metrics, lifetime);
  draw.timeline($("#timeline"), event.words);
  draw.transcript($("#transcript"), event.words, event.text);
  $("#replay").src = event.turn ? `/api/audio/${event.turn}` : "";
}

/** The whole session so far, a sparkline per metric. Dimmed while you are speaking. */
export function session(soFar, lifetime, series) {
  if (!soFar || !Object.keys(soFar).length) return;
  $("#session").hidden = false;
  draw.metrics($("#session-metrics"), soFar, lifetime, series);
}

/** The situation a mode has set up, e.g. a roleplay's scene. */
export function scene(text) {
  $("#scene").hidden = !text;
  $("#scene").textContent = text || "";
}

/** A mode's own result - rounds compared, a sentence matched. Hidden by `card(null)`. */
export function card(event) {
  $("#card").hidden = !event;
  if (!event) return;
  const rows = (event.rows || []).map((r) =>
    `<tr>${r.map((cell, i) => (i ? `<td>${escape(cell)}</td>` : `<th>${escape(cell)}</th>`))
      .join("")}</tr>`).join("");
  $("#card").innerHTML = `${event.title ? `<h2>${escape(event.title)}</h2>` : ""}
    ${rows ? `<table>${rows}</table>` : ""}
    ${event.text ? `<p>${escape(event.text)}</p>` : ""}`;
}

export function critique(text) {
  $("#critique").hidden = false;
  $("#critique").textContent = text;
}
