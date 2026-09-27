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

/* ───── views ───── */

function show(name) {
  document.querySelectorAll('.view').forEach((view) => {
    view.hidden = view.id !== `view-${name}`;
  });
  if (name === 'setup') endSession();
  if (name === 'history') loadTrend();
  if (name === 'settings') renderSettings($('settings-form'));
}

document.querySelectorAll('[data-go]').forEach((button) =>
  button.addEventListener('click', () => show(button.dataset.go)));

/* ───── setup: mode, then interviewer ───── */

async function loadModes() {
  const modes = await (await fetch('/api/modes')).json();
  $('mode-list').innerHTML = modes.map((m) => `
    <button class="card" data-mode="${m.name}" data-role="${m.endpoint}" aria-pressed="false">
      <b>${m.name}</b><span>${m.help}</span>
    </button>`).join('');
  $('mode-list').querySelectorAll('.card').forEach((card) =>
    card.addEventListener('click', () => pickMode(card)));
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
      : `~${b.latency}`;
    return `
      <button class="pick" data-key="${b.key}" ${b.blocked ? 'disabled' : ''}>
        <b>${b.label}${b.free ? '<span class="tag free">free</span>'
                              : `<span class="tag">${b.cost}</span>`}</b>
        <span class="cost">${yours}</span>
        <span class="meta">${b.blocked ? `unavailable — ${b.blocked}` : b.note}</span>
      </button>`;
  }).join('');
  $('backend-list').querySelectorAll('.pick').forEach((button) =>
    button.addEventListener('click', () => start(chosenMode, button.dataset.key)));
  if (!data.available) {
    $('backend-foot').textContent =
      'Nothing reachable: no internet, and LM Studio is not serving a usable model.';
  }
  $('backend-heading').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ───── practice ───── */

function start(mode, backend) {
  show('practice');
  $('crumb').textContent = `${mode} · ${backend}`;
  resetTurn();
  $('question').textContent = 'Connecting…';

  socket = new WebSocket(`ws://${location.host}/ws`);
  socket.binaryType = 'arraybuffer';
  socket.onopen = () => socket.send(JSON.stringify({ mode, backend }));
  socket.onmessage = (event) => {
    if (typeof event.data !== 'string') return playback.push(event.data);
    handle(JSON.parse(event.data));
  };
  socket.onclose = () => setMic(false, 'session ended');
}

function resetTurn() {
  $('result').hidden = true;
  $('critique').hidden = true;
  $('notice').hidden = true;
}

let questionParts = [];

function handle(event) {
  switch (event.type) {
    case 'ready':
      questionParts = [];
      $('question').textContent = 'Start whenever you are ready.';
      setMic(true, 'tap to answer  ·  or press space');
      break;
    case 'sentence':
      if (questionParts.length === 0) resetTurn();
      questionParts.push(event.speaker ? `${event.speaker}: ${event.text}` : event.text);
      $('question').textContent = questionParts.join(' ');
      break;
    case 'transcript':
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
  $('crumb').textContent = 'practice';
  $('mic').classList.remove('recording');
}

/* ───── history and settings ───── */

async function loadTrend() {
  render.trend($('trend'), await (await fetch('/api/trend')).json());
}

$('save').addEventListener('click', async (e) => {
  e.preventDefault();
  await saveSettings($('settings-form'));
  $('saved').hidden = false;
  setTimeout(() => { $('saved').hidden = true; }, 2000);
});

$('forget').addEventListener('click', async () => {
  if (!confirm('Delete every session, metric and recording? This cannot be undone.')) return;
  await fetch('/api/forget', { method: 'POST' });
  $('forget').textContent = 'Deleted.';
});

loadModes();
show('setup');
