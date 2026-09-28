import { Mic, Playback, meter } from './audio.js';
import * as render from './render.js';
import { renderSettings, saveSettings } from './settings.js';

const $ = (id) => document.getElementById(id);
const mic = new Mic();
const playback = new Playback();

let socket = null;
let recording = false;
let stopMeter = null;
let chosenMode = null;
let active = null;        // { mode, backend, session } while a session is running
let answered = 0;
let questionParts = [];

/* ───── remembering where you were ─────
   A refresh used to lose everything. The live session lives in sessionStorage so a
   reload reconnects to it; the last choice lives in localStorage so a new visit can
   skip setup. */

const LAST = 'coach.last';
const ACTIVE = 'coach.active';

const readJSON = (store, key) => {
  try { return JSON.parse(store.getItem(key) || 'null'); } catch { return null; }
};
const writeJSON = (store, key, value) => {
  try {
    if (value) store.setItem(key, JSON.stringify(value)); else store.removeItem(key);
  } catch { /* private mode: remembering is a convenience, not a requirement */ }
};

/* ───── views ───── */

function show(name) {
  document.querySelectorAll('.view').forEach((v) => { v.hidden = v.id !== `view-${name}`; });
  if (name === 'setup') endSession();
  if (name === 'history') loadTrend();
  if (name === 'settings') renderSettings($('settings-form'));
}

document.querySelectorAll('[data-go]').forEach((b) =>
  b.addEventListener('click', () => show(b.dataset.go)));

/* ───── setup ───── */

async function loadModes() {
  const modes = await (await fetch('/api/modes')).json();
  $('mode-list').innerHTML = modes.map((m) => `
    <button class="card" data-mode="${m.name}" data-role="${m.endpoint}" aria-pressed="false">
      <b>${m.name}</b><span>${m.help}</span>
    </button>`).join('');
  $('mode-list').querySelectorAll('.card').forEach((card) =>
    card.addEventListener('click', () => pickMode(card)));

  const last = readJSON(localStorage, LAST);
  if (last) {
    $('resume').hidden = false;
    $('resume').textContent = `Continue with ${last.mode} · ${last.backend}`;
    $('resume').onclick = () => start(last.mode, last.backend);
  }
}

function pickMode(card) {
  $('mode-list').querySelectorAll('.card')
    .forEach((c) => c.setAttribute('aria-pressed', String(c === card)));
  chosenMode = card.dataset.mode;
  loadBackends(card.dataset.role);
}

async function loadBackends(role) {
  const data = await (await fetch(`/api/backends?role=${role}`)).json();
  ['backend-heading', 'backend-list', 'backend-foot'].forEach((id) => { $(id).hidden = false; });
  $('backend-list').innerHTML = data.backends.map((b) => {
    const yours = b.samples
      ? `yours ${(b.measured_ms / 1000).toFixed(1)}s (n=${b.samples})`
      : b.latency;
    return `<button class="pick" data-key="${b.key}" ${b.blocked ? 'disabled' : ''}>
      <b>${b.label}${b.free ? '<span class="tag free">free</span>'
                            : `<span class="tag">${b.cost}</span>`}</b>
      <span class="cost">${yours}</span>
      <span class="meta">${b.blocked ? `unavailable — ${b.blocked}` : b.note}</span>
    </button>`;
  }).join('');
  $('backend-list').querySelectorAll('.pick').forEach((b) =>
    b.addEventListener('click', () => start(chosenMode, b.dataset.key)));
  if (!data.available) {
    $('backend-foot').textContent =
      'Nothing reachable: no internet, and LM Studio is not serving a usable model. '
      + 'Add an API key in settings, or start LM Studio.';
  }
}

/* ───── practice ───── */

function start(mode, backend, resume = null) {
  show('practice');
  active = { mode, backend, session: resume };
  answered = 0;
  questionParts = [];
  resetTurn();
  $('crumb').textContent = `${mode} · ${backend}`;
  $('question').textContent = resume ? 'Reconnecting…' : 'Waiting for the interviewer…';
  setMic(false, 'connecting');
  $('status').textContent = '';

  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.binaryType = 'arraybuffer';
  socket.onopen = () => socket.send(JSON.stringify({ mode, backend, resume }));
  socket.onmessage = (e) =>
    (typeof e.data === 'string' ? handle(JSON.parse(e.data)) : playback.push(e.data));
  socket.onerror = () => {
    $('question').textContent = 'Could not reach the server.';
    setMic(false, 'is it still running?');
  };
  socket.onclose = () => {
    if (active) setMic(false, 'disconnected — reload to reconnect');
  };
}

function resetTurn() {
  $('result').hidden = true;
  $('critique').hidden = true;
  $('notice').hidden = true;
}

function handle(event) {
  switch (event.type) {
    case 'ready':
      active.session = event.session;
      answered = event.answered || 0;
      writeJSON(sessionStorage, ACTIVE, active);
      writeJSON(localStorage, LAST, { mode: active.mode, backend: active.backend });
      updateStatus(event.model, event.local);
      break;
    case 'sentence':
      if (questionParts.length === 0) resetTurn();
      questionParts.push(event.speaker ? `${event.speaker}: ${event.text}` : event.text);
      $('question').textContent = questionParts.join(' ');
      break;
    case 'transcript':
      answered += 1;
      showAnswer(event);
      break;
    case 'thinking':
      setMic(false, `${event.text}…`);
      break;
    case 'critique':
      $('critique').hidden = false;
      $('critique').textContent = event.text;
      break;
    case 'turn_done':
      playback.idle().then(() => { questionParts = []; setMic(true, 'tap to answer'); });
      break;
    case 'notice':
    case 'error':
      $('notice').hidden = false;
      $('notice').textContent = event.text;
      setMic(true, 'tap to answer');
      break;
  }
  updateStatus();
}

function updateStatus(model, local) {
  if (model) updateStatus.detail = `${model} · ${local ? 'on this machine' : 'cloud'}`;
  const count = answered === 0 ? 'no answers yet' : `${answered} answered`;
  $('status').textContent = `${count}  ·  ${updateStatus.detail || ''}`;
}

function showAnswer(event) {
  $('result').hidden = false;
  if (event.metrics) render.metrics($('metrics'), event.metrics);
  render.timeline($('timeline'), event.words);
  render.transcript($('transcript'), event.words, event.text);
  $('replay').src = event.turn ? `/api/audio/${event.turn}` : '';
  setMic(false, 'thinking…');
}

function setMic(enabled, label) {
  $('mic').disabled = !enabled;
  $('mic-label').textContent = label;
}

async function toggleRecording() {
  if ($('mic').disabled && !recording) return;
  if (!recording) {
    try {
      await mic.start((chunk) => socket?.readyState === 1 && socket.send(chunk));
    } catch {
      $('notice').hidden = false;
      $('notice').textContent =
        'No microphone access. Allow it in your browser, then tap again.';
      return;
    }
    recording = true;
    resetTurn();
    $('mic').classList.add('recording');
    $('level').classList.add('on');
    stopMeter = meter($('level'), mic);
    setMic(true, 'tap when you are done');
  } else {
    recording = false;
    mic.stop();
    stopMeter?.();
    $('mic').classList.remove('recording');
    $('level').classList.remove('on');
    socket?.send(JSON.stringify({ type: 'end_answer' }));
    setMic(false, 'transcribing…');
  }
}

$('mic').addEventListener('click', toggleRecording);
document.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && !$('view-practice').hidden && e.target.tagName !== 'TEXTAREA') {
    e.preventDefault();
    toggleRecording();
  }
});

function endSession() {
  if (recording) { mic.stop(); stopMeter?.(); recording = false; }
  playback.stop();
  if (socket?.readyState === 1) socket.send(JSON.stringify({ type: 'quit' }));
  socket?.close();
  socket = null;
  active = null;
  writeJSON(sessionStorage, ACTIVE, null);
  $('crumb').textContent = 'practice';
  $('mic').classList.remove('recording');
}

/* ───── history and settings ───── */

async function loadTrend() {
  render.trend($('trend'), await (await fetch('/api/trend')).json());
}

$('save').addEventListener('click', async (e) => {
  e.preventDefault();
  $('save').disabled = true;
  await saveSettings($('settings-form'));
  await renderSettings($('settings-form'));   // re-read, so you see what actually stuck
  $('save').disabled = false;
  $('saved').hidden = false;
  setTimeout(() => { $('saved').hidden = true; }, 2500);
});

$('forget').addEventListener('click', async () => {
  if (!confirm('Delete every session, metric and recording? This cannot be undone.')) return;
  await fetch('/api/forget', { method: 'POST' });
  $('forget').textContent = 'Deleted.';
});

/* ───── boot ───── */

await loadModes();
const live = readJSON(sessionStorage, ACTIVE);
if (live?.mode && live?.backend) start(live.mode, live.backend, live.session);
else show('setup');
