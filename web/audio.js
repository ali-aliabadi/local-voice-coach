// Microphone in, speaker out. The only two things the browser does that Python cannot.

const SAMPLE_RATE = 16000;   // what Whisper wants, so the browser resamples, not us

export class Mic {
  constructor() {
    this.context = null;
    this.stream = null;
    this.level = 0;
  }

  /** Ask once, keep the permission. Throws if the user refuses or there's no mic. */
  async open() {
    if (this.context) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    this.context = new AudioContext({ sampleRate: SAMPLE_RATE });
    await this.context.audioWorklet.addModule('/static/recorder.worklet.js');
  }

  /** Start streaming Float32 chunks to `onChunk`. Also tracks a level for the meter. */
  async start(onChunk) {
    await this.open();
    if (this.context.state === 'suspended') await this.context.resume();
    this.source = this.context.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.context, 'recorder');
    this.node.port.onmessage = (event) => {
      const samples = event.data;
      let sum = 0;
      for (let i = 0; i < samples.length; i += 16) sum += samples[i] * samples[i];
      this.level = Math.sqrt(sum / (samples.length / 16));
      onChunk(samples.buffer);
    };
    this.source.connect(this.node);
  }

  stop() {
    this.source?.disconnect();
    this.node?.disconnect();
    this.source = this.node = null;
    this.level = 0;
  }
}

export class Playback {
  /** Plays WAV blobs strictly in order, so sentences never overlap or swap. */
  constructor() {
    this.queue = [];
    this.element = new Audio();
    this.playing = false;
    this.waiters = [];
    // Browsers block audio until the page has been interacted with. On a reload straight
    // back into a session there has been no click, so the reply would play into
    // the void. Tell someone instead of swallowing it.
    this.onBlocked = null;
    this.blocked = false;
    this.turn = [];     // the current reply's clips, kept so "again" needs no round trip
    this.keep = true;   // false for a replay, so "again" replays the original speed
    this.quiet = 0;     // performance.now() when the partner last fell silent
  }

  push(bytes) {
    const blob = new Blob([bytes], { type: 'audio/wav' });
    if (this.keep) this.turn.push(blob);
    this.keep = true;
    this.queue.push(blob);
    if (!this.playing) this.#next();
  }

  /** A new reply is starting: forget the last one's clips. */
  newTurn() { this.turn = []; }

  /** The current reply again, from the top. */
  again() {
    this.stop();
    this.queue.push(...this.turn);
    this.#next();
  }

  #next() {
    const blob = this.queue.shift();
    if (!blob) {
      this.playing = false;
      this.quiet = performance.now();
      this.waiters.splice(0).forEach((resolve) => resolve());
      return;
    }
    this.playing = true;
    const url = URL.createObjectURL(blob);
    this.element.src = url;
    const advance = () => { URL.revokeObjectURL(url); this.#next(); };
    this.element.onended = advance;
    this.element.onerror = advance;
    this.element.play().then(() => { this.blocked = false; }).catch((error) => {
      if (error?.name === "NotAllowedError" && !this.blocked) {
        this.blocked = true;
        this.onBlocked?.();
      }
      advance();
    });
  }

  /** Resolves once everything queued has finished playing. */
  idle() {
    if (!this.playing && this.queue.length === 0) return Promise.resolve();
    return new Promise((resolve) => this.waiters.push(resolve));
  }

  stop() {
    this.queue.length = 0;
    this.element.pause();
    if (this.playing) this.quiet = performance.now();
    this.playing = false;
    this.waiters.splice(0).forEach((resolve) => resolve());
  }
}

/**
 * Hands-free: call `done` once you have spoken and then been quiet for `silence` seconds,
 * or after `patience` seconds if you never start. Returns a function that stops watching.
 * `silence` should sit well above the pause threshold: a pause mid-thought is exactly
 * what is being practised, and cutting it off would punish it.
 */
export const VOICE_LEVEL = 0.015;  // calibration knob: the mic level that counts as speech
export function untilSilence(mic, { silence, patience = 30, done, tick = 100 }) {
  const began = Date.now();
  let spoke = false;
  let quietSince = null;
  const timer = setInterval(() => {
    const now = Date.now();
    if (mic.level > VOICE_LEVEL) { spoke = true; quietSince = null; return; }
    quietSince ??= now;
    if ((spoke && now - quietSince >= silence * 1000) || (!spoke && now - began >= patience * 1000)) {
      clearInterval(timer);
      done();
    }
  }, tick);
  return () => clearInterval(timer);
}

/**
 * Hybrid: the mic stays open and your voice starts the answer. Feed it every chunk heard
 * between answers; it returns the chunks to send once speech has begun, the last PREROLL
 * of them, so the syllable that crossed the threshold is not cut off. `needed` chunks in
 * a row must be loud: over the partner's voice, one loud chunk is too easily an echo.
 */
export const CHUNK_MS = 256;       // recorder.worklet.js posts 4096 samples at 16kHz
export const PREROLL = 4;          // a second of audio from before the voice was noticed
export const CUT_IN_LEVEL = 0.05;  // calibration knob: louder than the partner's echo
export function onset() {
  const kept = [];
  let loud = 0;
  return (chunk, level, threshold, needed = 1) => {
    kept.push(chunk);
    if (kept.length > PREROLL) kept.shift();
    loud = level > threshold ? loud + 1 : 0;
    if (loud < needed) return null;
    loud = 0;
    return kept.splice(0);
  };
}

/** The little bar under the mic button. Rendered from Mic.level. */
export function meter(canvas, mic) {
  const context = canvas.getContext('2d');
  const bars = 28;
  const history = new Array(bars).fill(0);
  let running = true;

  (function frame() {
    if (!running) return;
    history.push(Math.min(1, mic.level * 7));
    history.shift();
    const style = getComputedStyle(document.body);
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = style.getPropertyValue('--accent').trim() || '#4a7c6f';
    const width = canvas.width / bars;
    history.forEach((value, i) => {
      const height = Math.max(2, value * canvas.height);
      context.fillRect(i * width, (canvas.height - height) / 2, width - 2, height);
    });
    requestAnimationFrame(frame);
  })();

  return () => { running = false; };
}
