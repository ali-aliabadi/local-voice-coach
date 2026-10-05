// Drawing for a single answer: the numbers, the shape of the answer over time, and the
// transcript with every filler marked. Trend charts live in chart.js.

import { SERIES, moved, verdict } from "./chart.js";

const escape = (text) =>
  String(text ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

const LABEL = {
  wpm: "words / min",
  fillers: "fillers / 100 words",
  pauses: "pauses / minute",
  lead_in: "before you spoke",
};

/**
 * The four numbers, each with a plain-language verdict.
 *
 * A bare "118 wpm" tells you nothing - the whole reason to measure is to know whether
 * that was good. `compare` is your own running average, when there is one to beat.
 */
export function metrics(target, m, compare = null, series = null) {
  target.innerHTML = Object.keys(SERIES).map((key) => {
    const value = m[key] ?? 0;
    const state = verdict(key, value);
    const spec = SERIES[key];
    const shift = compare ? moved(key, value, compare[key]) : null;
    const against = shift
      ? `<span class="against ${shift.better ? "up" : "down"}">${shift.text} than usual</span>`
      : "";
    return `<div class="metric">
      <b>${spec.format(value)}</b>
      <span>${LABEL[key]}</span>
      <span class="verdict ${state.state}">${state.text}</span>
      ${against}
      ${series ? spark(key, series.map((s) => s[key] ?? 0)) : ""}
    </div>`;
  }).join("");
}

/**
 * One metric across this session's answers, a point per answer. Fixed scale with the goal
 * band, like the trend charts: a flat session has to look flat.
 */
function spark(key, values) {
  if (values.length < 2) return "";
  const { domain: [lo, hi], goal: [glo, ghi] } = SERIES[key];
  const W = 120, H = 26;
  const y = (v) => H - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * H;
  const x = (i) => (i / (values.length - 1)) * W;
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
      role="img" aria-label="${SERIES[key].label}, answer by answer">
    <rect x="0" y="${y(ghi)}" width="${W}" height="${Math.max(1, y(glo) - y(ghi))}"
      fill="var(--goal)"/>
    <polyline points="${values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}"
      fill="none" stroke="var(--accent)" stroke-width="1.5" vector-effect="non-scaling-stroke"
      stroke-linejoin="round"/>
  </svg>`;
}

/** The answer as text, with every filler marked. You see them, not a count. */
export function transcript(target, words, fallback) {
  if (!words?.length) {
    target.textContent = fallback;
    return;
  }
  target.innerHTML = words.map((w) => {
    if (w.filler) return `<span class="filler" title="filler word">${escape(w.word)}</span>`;
    if (w.unclear) {
      return `<span class="unclear" title="the transcriber was unsure of this word: maybe
        unclear, maybe misheard">${escape(w.word)}</span>`;
    }
    return escape(w.word);
  }).join(" ");
  if (words.some((w) => w.unclear && !w.filler)) {
    target.insertAdjacentHTML("beforeend", `<small class="unclear-key">dotted: the
      transcriber was unsure — a word that may not have come out clearly</small>`);
  }
}

/**
 * The answer as a strip: speech in the accent colour, silences as gaps, on a real time
 * axis. A two-second hole is visceral in a way `longest_pause: 2.0` never is.
 */
export function timeline(target, words) {
  if (!words?.length) { target.innerHTML = ""; return; }
  const end = words[words.length - 1].end || 1;
  const W = 680, H = 30;
  const x = (t) => (t / end) * W;

  const lead = words[0].start > 0
    ? `<rect x="0" y="2" width="${x(words[0].start).toFixed(1)}" height="${H - 4}"
        fill="var(--quiet)"/>`
    : "";

  const gaps = words.filter((w) => w.pause > 0).map((w) => {
    const from = x(w.start - w.pause);
    return `<rect x="${from.toFixed(1)}" y="2" width="${(x(w.start) - from).toFixed(1)}"
      height="${H - 4}" fill="var(--gap)"/>`;
  });

  const speech = words.map((w) => {
    const left = x(w.start);
    return `<rect x="${left.toFixed(1)}" y="9" width="${Math.max(1, x(w.end) - left).toFixed(1)}"
      height="12" rx="1" fill="${w.filler ? "var(--warn)" : "var(--accent)"}"/>`;
  });

  // A ruler, because "was that gap half a second or three?" is the whole question.
  const step = end > 90 ? 30 : end > 30 ? 10 : end > 12 ? 5 : 2;
  const ruler = [];
  for (let t = 0; t <= end; t += step) {
    ruler.push(`<line x1="${x(t).toFixed(1)}" x2="${x(t).toFixed(1)}" y1="0" y2="4"
      stroke="var(--line)"/><text x="${x(t).toFixed(1)}" y="14" class="tick"
      text-anchor="${t === 0 ? "start" : "middle"}">${t}s</text>`);
  }

  target.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" class="strip"
         role="img" aria-label="Your answer over time. Gaps are silences.">
      ${lead}${gaps.join("")}${speech.join("")}
    </svg>
    <svg viewBox="0 0 ${W} 18" preserveAspectRatio="none" class="ruler" aria-hidden="true">
      ${ruler.join("")}
    </svg>
    <p class="foot legend">
      <span class="chip quiet"></span> before you started
      <span class="chip gap"></span> a pause
      <span class="chip fill"></span> filler word
      <span class="dur">${end.toFixed(1)}s</span>
    </p>`;
}
