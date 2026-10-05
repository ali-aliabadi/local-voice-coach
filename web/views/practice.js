// The practice screen. While you speak there is only the mic: the session panel dims, so
// there is nothing to perform for. Between answers you see how this whole session is
// going, the clock against your goal, and your last answer in detail. What the partner
// says is blurred until you ask for it - listening comes first.
//
// This file is the conversation: the socket, its events, the mic. screen.js draws.

import { Mic, Playback, meter, untilSilence } from "../audio.js";
import * as clock from "../clock.js";
import { get } from "../form.js";
import { go } from "../router.js";
import * as screen from "../screen.js";
import { keepLast } from "./today.js";

const { $ } = screen;
const ACTIVE = "coach.active";
const mic = new Mic();
const playback = new Playback();

let socket = null;
let recording = false;
let stopMeter = null;
let session = null;
let answered = 0;
let detail = "";
let waited = null;     // ms from the end of your last answer to the first sound back
let parts = [];        // the partner's sentences so far this turn
let lifetime = null;   // your running average, so each answer can be measured against it
let series = [];       // this session's answers, one point each on the session panel
let goal = 0;          // minutes the user set out to practise
let goalPending = false;
let stopClock = null;
let helped = new Set();  // what you needed to follow this reply: again, slower, text
let handsFree = null;  // { silence } when the mic opens and closes by itself
let stopWatch = null;
let muted = false;     // you cut in: drop the rest of this reply
let limit = 0;         // seconds the next answer may run, when a mode sets one
let stopCountdown = null;

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
  const saved = resumable();
  const mode = query.get("mode") || saved?.mode;
  const backend = query.get("backend") || saved?.backend;
  if (!mode || !backend) return go("/modes", true);

  screen.mount(node);
  playback.onBlocked = () => screen.notice(
    "Your browser blocked audio until you interact with the page. Click anywhere, "
    + "and you will hear the next reply.");
  $("#mic").addEventListener("click", toggle);
  $("#end").addEventListener("click", finish);
  $("#again").addEventListener("click", () => { helped.add("again"); playback.again(); });
  $("#slower").addEventListener("click", () => {
    helped.add("slower");
    playback.stop();
    socket?.send(JSON.stringify({ type: "slower" }));
  });
  const fresh = query.get("mode");
  if (fresh) keepLast(mode, backend);
  connect(mode, backend, fresh ? null : saved?.session, Number(query.get("goal")) || 0);
  get("/api/progress").then(({ totals }) => { lifetime = totals.answers ? totals : null; });
}

export async function leave() {
  close();
}

function connect(mode, backend, resume, goalMinutes) {
  session = resume || null;
  answered = 0;
  parts = [];
  series = [];
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.binaryType = "arraybuffer";
  socket.onopen = () =>
    socket.send(JSON.stringify({ mode, backend, resume, goal: goalMinutes }));
  socket.onmessage = (e) => {
    if (typeof e.data === "string") handle(JSON.parse(e.data), mode, backend);
    else if (!muted) playback.push(e.data);
  };
  socket.onerror = () => {
    screen.say("Could not reach the server.", false);
    screen.mic(false, "is it still running?");
  };
  socket.onclose = () => { if (socket) screen.mic(false, "disconnected — reload to reconnect"); };
}

function handle(event, mode, backend) {
  switch (event.type) {
    case "ready":
      session = event.session;
      answered = event.answered || 0;
      if (!parts.length) screen.say(`Waiting for the ${event.partner}…`, false);
      detail = `${event.model} · ${event.local ? "on this machine" : "cloud"}`;
      remember({ mode, backend, session });
      goal = event.goal || 0;
      stopClock?.();
      stopClock = clock.start({
        label: $("#clock"), bar: $("#goalfill"), elapsed: event.elapsed, goal, reached,
      });
      handsFree = event.hands_free ? { silence: event.silence } : null;
      series = event.answers || [];
      if (series.length) screen.session(event.so_far, lifetime, series);
      break;
    case "audio":
      playback.keep = !event.replay;
      break;
    case "sentence":
      if (muted) break;
      if (parts.length === 0) {
        screen.reset();
        screen.mic(true, "listen · tap to cut in");
        playback.newTurn();
        helped = new Set();
      }
      parts.push(event.speaker ? `${event.speaker}: ${event.text}` : event.text);
      screen.say(parts.join(" "), true);
      break;
    case "transcript":
      answered += 1;
      series.push(event.metrics || {});
      screen.session(event.session, lifetime, series);
      screen.answer(event, lifetime);
      screen.wait("waiting for a reply");
      break;
    case "thinking":
      screen.wait(event.text);
      break;
    case "scene":
      screen.scene(event.text);
      break;
    case "card":
      screen.card(event);
      break;
    case "limit":
      limit = event.seconds;
      break;
    case "critique":
      screen.critique(event.text);
      break;
    case "turn_done":
      if (event.wait_ms) waited = event.wait_ms;
      muted = false;
      playback.idle().then(() => {
        parts = [];
        if (recording) return;  // you cut in: already answering
        if (handsFree) toggle();
        else screen.mic(true, "tap to answer");
      });
      break;
    case "notice":
    case "error":
      screen.notice(event.text, { retry: event.retry ? retry : null });
      screen.mic(true, "tap to answer");
      break;
  }
  screen.status(answered, waited ? `replied in ${(waited / 1000).toFixed(1)}s · ${detail}` : detail);
}

/** Ask for the last reply again, with the same answer: nobody should have to repeat it. */
function retry() {
  socket?.send(JSON.stringify({ type: "retry" }));
  screen.wait("trying again");
}

/** The goal passed. Never interrupt an answer for it: wait until it is finished. */
function reached() {
  if (recording) { goalPending = true; return; }
  goalPending = false;
  clock.chime();
  screen.notice(
    `Goal reached: ${goal} minutes. Keep going if you like, or end the session below.`,
    { good: true });
}

async function toggle() {
  if ($("#mic").disabled && !recording) return;
  if (!recording) {
    try {
      await mic.start((chunk) => socket?.readyState === 1 && socket.send(chunk));
    } catch {
      screen.notice("No microphone access. Allow it, then tap again.");
      return;
    }
    recording = true;
    if (playback.playing) muted = true;  // cutting in: the rest of this reply is dropped
    playback.stop();  // and a replay must not end up in the recording
    if (screen.reading()) helped.add("text");
    // Sent even when empty: "followed by ear" has to be recorded, not assumed.
    socket?.send(JSON.stringify({ type: "helped", kinds: [...helped] }));
    helped = new Set();
    $("#listen-tools").hidden = true;
    screen.reset();
    screen.card(null);
    $("#session").classList.add("dim");
    $("#mic").setAttribute("aria-pressed", "true");
    $("#mic").classList.add("recording");
    $("#level").classList.add("on");
    stopMeter = meter($("#level"), mic);
    if (handsFree) {
      stopWatch = untilSilence(mic, { silence: handsFree.silence, done: () => recording && toggle() });
      screen.mic(true, "listening · just talk");
    } else {
      screen.mic(true, "tap when you are done");
    }
    if (limit) {
      stopCountdown = clock.countdown($("#mic-label"), limit, () => recording && toggle());
      limit = 0;
    }
  } else {
    recording = false;
    mic.stop();
    stopMeter?.();
    stopWatch?.();
    stopCountdown?.();
    $("#session").classList.remove("dim");
    $("#mic").setAttribute("aria-pressed", "false");
    $("#mic").classList.remove("recording");
    $("#level").classList.remove("on");
    socket?.send(JSON.stringify({ type: "end_answer" }));
    screen.wait("transcribing");
    if (goalPending) reached();
  }
}

function close() {
  stopClock?.();
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
