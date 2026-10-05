// The session clock: how long you have practised, against the goal you set out with.
// Counts from the server's start time, so a reload picks up where it was.

const pad = (n) => String(Math.floor(n)).padStart(2, "0");
export const mmss = (seconds) => (seconds >= 3600
  ? `${Math.floor(seconds / 3600)}:${pad((seconds % 3600) / 60)}:${pad(seconds % 60)}`
  : `${pad(seconds / 60)}:${pad(seconds % 60)}`);

export const GOALS = [15, 30, 45, 60, 0];   // minutes; 0 is "no goal"

/** The goal you picked last time, so the habit does not need re-deciding every day. */
export function lastGoal() {
  try { return Number(localStorage.getItem("coach.goal") ?? 30); } catch { return 30; }
}
export function keepGoal(minutes) {
  try { localStorage.setItem("coach.goal", String(minutes)); } catch { /* convenience only */ }
}

/**
 * Tick `label` every second and fill `bar` toward the goal. `reached` is called once,
 * when the goal passes. Returns a function that stops the clock.
 */
export function start({ label, bar, elapsed, goal, reached }) {
  const began = Date.now() - elapsed * 1000;
  let done = !goal || elapsed >= goal * 60;
  const tick = () => {
    const seconds = (Date.now() - began) / 1000;
    label.textContent = goal ? `${mmss(seconds)} / ${mmss(goal * 60)}` : mmss(seconds);
    bar.style.width = goal ? `${Math.min(100, (seconds / (goal * 60)) * 100)}%` : "0";
    if (!done && seconds >= goal * 60) {
      done = true;
      reached();
    }
  };
  tick();
  const timer = setInterval(tick, 1000);
  return () => clearInterval(timer);
}

/** "0:45 left" on `label`, then `done` at zero. Returns a function that stops it. */
export function countdown(label, seconds, done) {
  const ends = Date.now() + seconds * 1000;
  const tick = () => {
    const left = Math.max(0, Math.ceil((ends - Date.now()) / 1000));
    label.textContent = `${Math.floor(left / 60)}:${pad(left % 60)} left · tap when you are done`;
    if (left === 0) { clearInterval(timer); done(); }
  };
  const timer = setInterval(tick, 250);
  tick();
  return () => clearInterval(timer);
}

/** Two soft notes. Gentle on purpose: it should not startle you mid-thought. */
export function chime() {
  try {
    const context = new AudioContext();
    [660, 880].forEach((hz, i) => {
      const tone = context.createOscillator();
      const gain = context.createGain();
      const at = context.currentTime + i * 0.18;
      tone.frequency.value = hz;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.08, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.35);
      tone.connect(gain).connect(context.destination);
      tone.start(at);
      tone.stop(at + 0.4);
    });
  } catch { /* no audio: the on-screen notice still says it */ }
}
