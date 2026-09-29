// Focus mode: one question, nothing else. Metrics appear after the answer, never during
// it — a dashboard while you speak is something to hide behind, and real interviews have
// none.

import { Mic, Playback, meter } from "../audio.js";
import * as draw from "../render.js";
import { go } from "../router.js";

const ACTIVE = "coach.active";
const mic = new Mic();
const playback = new Playback();

let socket = null;
let recording = false;
let stopMeter = null;
let session = null;
let answered = 0;
let detail = "";
let parts = [];
let root = null;

const $ = (sel) => root.querySelector(sel);

const remember = (value) => {
  try {
    if (value) sessionStorage.setItem(ACTIVE, JSON.stringify(value));
    else sessionStorage.removeItem(ACTIVE);
  } catch { /* private mode: resuming is a convenience, not a requirement */ }
};

export function resumable() {
  try { return JSON.parse(sessionStorage.getItem(ACTIVE) || "null"); } catch { return null; }
}

export async function render(node, _params, query) {
  root = node;
  const saved = resumable();
  const mode = query.get("mode") || saved?.mode;
  const backend = query.get("backend") || saved?.backend;
  if (!mode || !backend) return go("/modes", true);

  root.innerHTML = `
    <p class="status" id="status"></p>
    <p class="question" id="question">Waiting for the interviewer…</p>
    <div class="stage">
      <button id="mic" class="mic" disabled aria-label="Answer"></button>
      <p class="mic-label" id="mic-label">connecting</p>
      <canvas id="level" width="240" height="28" aria-hidden="true"></canvas>
      <p class="hint">space bar works too · answer out loud, as if it were real</p>
    </div>
    <section id="result" hidden>
      <div class="metrics" id="metrics"></div>
      <div id="timeline"></div>
      <p class="transcript" id="transcript"></p>
      <div class="row">
        <audio id="replay" controls preload="none"></audio>
        <span class="hint">hearing your own hesitation teaches faster than the number</span>
      </div>
      <article id="critique" class="critique" hidden></article>
    </section>
    <p class="notice" id="notice" hidden></p>
    <button class="link end" id="end">end session and review it</button>`;

  $("#mic").addEventListener("click", toggle);
  $("#end").addEventListener("click", finish);
  connect(mode, backend, query.get("mode") ? null : saved?.session);
}

export async function leave() {
  close();
}

function connect(mode, backend, resume) {
  session = resume || null;
  answered = 0;
  parts = [];
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.binaryType = "arraybuffer";
  socket.onopen = () => socket.send(JSON.stringify({ mode, backend, resume }));
  socket.onmessage = (e) =>
    (typeof e.data === "string" ? handle(JSON.parse(e.data), mode, backend) : playback.push(e.data));
  socket.onerror = () => {
    $("#question").textContent = "Could not reach the server.";
    setMic(false, "is it still running?");
  };
  socket.onclose = () => { if (socket) setMic(false, "disconnected — reload to reconnect"); };
}

function handle(event, mode, backend) {
  switch (event.type) {
    case "ready":
      session = event.session;
      answered = event.answered || 0;
      detail = `${event.model} · ${event.local ? "on this machine" : "cloud"}`;
      remember({ mode, backend, session });
      break;
    case "sentence":
      if (parts.length === 0) reset();
      parts.push(event.speaker ? `${event.speaker}: ${event.text}` : event.text);
      $("#question").textContent = parts.join(" ");
      break;
    case "transcript":
      answered += 1;
      showAnswer(event);
      break;
    case "thinking":
      setMic(false, `${event.text}…`);
      break;
    case "critique":
      $("#critique").hidden = false;
      $("#critique").textContent = event.text;
      break;
    case "turn_done":
      playback.idle().then(() => { parts = []; setMic(true, "tap to answer"); });
      break;
    case "notice":
    case "error":
      $("#notice").hidden = false;
      $("#notice").textContent = event.text;
      setMic(true, "tap to answer");
      break;
  }
  status();
}

function status() {
  $("#status").textContent =
    `${answered === 0 ? "no answers yet" : `${answered} answered`}  ·  ${detail}`;
}

function reset() {
  $("#result").hidden = true;
  $("#critique").hidden = true;
  $("#notice").hidden = true;
}

function showAnswer(event) {
  $("#result").hidden = false;
  if (event.metrics) draw.metrics($("#metrics"), event.metrics);
  draw.timeline($("#timeline"), event.words);
  draw.transcript($("#transcript"), event.words, event.text);
  $("#replay").src = event.turn ? `/api/audio/${event.turn}` : "";
  setMic(false, "thinking…");
}

function setMic(enabled, label) {
  $("#mic").disabled = !enabled;
  $("#mic-label").textContent = label;
}

async function toggle() {
  if ($("#mic").disabled && !recording) return;
  if (!recording) {
    try {
      await mic.start((chunk) => socket?.readyState === 1 && socket.send(chunk));
    } catch {
      $("#notice").hidden = false;
      $("#notice").textContent = "No microphone access. Allow it, then tap again.";
      return;
    }
    recording = true;
    reset();
    $("#mic").classList.add("recording");
    $("#level").classList.add("on");
    stopMeter = meter($("#level"), mic);
    setMic(true, "tap when you are done");
  } else {
    recording = false;
    mic.stop();
    stopMeter?.();
    $("#mic").classList.remove("recording");
    $("#level").classList.remove("on");
    socket?.send(JSON.stringify({ type: "end_answer" }));
    setMic(false, "transcribing…");
  }
}

function close() {
  if (recording) { mic.stop(); stopMeter?.(); recording = false; }
  playback.stop();
  if (socket?.readyState === 1) socket.send(JSON.stringify({ type: "quit" }));
  const open = socket;
  socket = null;
  open?.close();
  remember(null);
}

function finish() {
  const id = session;
  close();
  go(id && answered ? `/history/${id}` : "/modes");
}

document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || !socket) return;
  if (event.target.tagName === "TEXTAREA" || event.target.tagName === "INPUT") return;
  event.preventDefault();
  toggle();
});
