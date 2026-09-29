// Trend charts.
//
// Every scale here is FIXED, not fitted to the data. Fitting min-to-max was the old
// behaviour and it lied: a week where fillers went 3.0 -> 3.1 -> 2.9 was stretched to
// full height and read as a dramatic swing. A stable scale means flat looks flat, and a
// real improvement looks like one.

const W = 680;
const H = 132;
const PAD = { top: 16, right: 16, bottom: 26, left: 38 };

// domain: the fixed window. goal: where you are trying to get to.
export const SERIES = {
  wpm: {
    label: "words per minute", domain: [60, 180], goal: [140, 160], better: "up",
    goalNote: "natural conversational pace",
    format: (v) => String(Math.round(v)),
  },
  fillers: {
    label: "filler words per answer", domain: [0, 8], goal: [0, 2], better: "down",
    goalNote: "barely noticeable",
    format: (v) => v.toFixed(1),
  },
  pauses: {
    label: "pauses per answer", domain: [0, 8], goal: [0, 2], better: "down",
    goalNote: "sounds fluent",
    format: (v) => v.toFixed(1),
  },
  lead_in: {
    label: "seconds before you start", domain: [0, 6], goal: [0, 1.5], better: "down",
    goalNote: "answering, not bracing",
    format: (v) => `${v.toFixed(1)}s`,
  },
};

const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v));

/**
 * How a change reads in a sentence.
 *
 * Spelled out rather than assembled from an arrow plus a number: an up arrow next to
 * "1.9 fillers" is ambiguous - it went down, which is the good direction. Words carry
 * both facts at once.
 */
export const PHRASE = {
  wpm: (d, better) => `${Math.round(Math.abs(d))} wpm ${better ? "faster" : "slower"}`,
  fillers: (d, better) => `${Math.abs(d).toFixed(1)} ${better ? "fewer" : "more"} fillers`,
  pauses: (d, better) => `${Math.abs(d).toFixed(1)} ${better ? "fewer" : "more"} pauses`,
  lead_in: (d, better) => `${Math.abs(d).toFixed(1)}s ${better ? "quicker" : "slower"} to start`,
};

/** How much a number has to move before it is worth mentioning rather than noise. */
export const MOVED = { wpm: 4, fillers: 0.4, pauses: 0.4, lead_in: 0.3 };

export function moved(key, now, before) {
  const diff = (now ?? 0) - (before ?? 0);
  if (before == null || Math.abs(diff) < MOVED[key]) return null;
  const better = SERIES[key].better === "up" ? diff > 0 : diff < 0;
  return { better, text: PHRASE[key](diff, better) };
}

export function inGoal(key, value) {
  const [lo, hi] = SERIES[key].goal;
  return value >= lo && value <= hi;
}

/** Plain-language verdict for a value. Numbers mean nothing without this. */
export function verdict(key, value) {
  const spec = SERIES[key];
  const [lo, hi] = spec.goal;
  if (value >= lo && value <= hi) return { state: "good", text: `on target — ${spec.goalNote}` };
  const away = value > hi ? value - hi : lo - value;
  const close = away <= (spec.better === "up" ? 15 : 1);
  const direction = spec.better === "up" ? "faster" : "fewer";
  const unit = key === "lead_in" ? "shorter" : direction;
  return close
    ? { state: "near", text: `nearly there — target is ${spec.format(hi || lo)}` }
    : { state: "far", text: `aiming for ${spec.format(hi)} or ${unit}` };
}

function scale(spec, values) {
  const [lo, hi] = spec.domain;
  // Keep the round domain in the normal case; only grow it, and only to the next round
  // step, when someone genuinely goes off the top of it.
  const peak = Math.max(...values);
  const step = (hi - lo) / 4;
  const top = peak > hi ? lo + Math.ceil((peak - lo) / step) * step : hi;
  return {
    x: (i, n) => PAD.left + (n < 2 ? (W - PAD.left - PAD.right) / 2
      : (i / (n - 1)) * (W - PAD.left - PAD.right)),
    y: (v) => PAD.top + (1 - (clamp(v, [lo, top]) - lo) / (top - lo))
      * (H - PAD.top - PAD.bottom),
    lo, top,
  };
}

function chart(key, rows) {
  const spec = SERIES[key];
  const label = shortener(rows);
  const values = rows.map((r) => r[key] ?? 0);
  const s = scale(spec, values);
  const n = values.length;
  const points = values.map((v, i) => [s.x(i, n), s.y(v)]);
  const last = values[n - 1];
  const first = values[0];
  const delta = last - first;
  const improving = spec.better === "up" ? delta > 0 : delta < 0;
  const state = verdict(key, last);

  const band = `<rect x="${PAD.left}" y="${s.y(spec.goal[1])}"
    width="${W - PAD.left - PAD.right}"
    height="${Math.max(2, s.y(spec.goal[0]) - s.y(spec.goal[1]))}"
    fill="var(--goal)"/>`;

  const ticks = [s.lo, (s.lo + s.top) / 2, s.top].map((v) => `
    <line x1="${PAD.left}" x2="${W - PAD.right}" y1="${s.y(v)}" y2="${s.y(v)}"
          stroke="var(--line)" stroke-width="1"/>
    <text x="${PAD.left - 8}" y="${s.y(v) + 4}" class="tick" text-anchor="end">
      ${spec.format(v)}</text>`).join("");

  const line = `<polyline points="${points.map((p) => p.join(",")).join(" ")}"
    fill="none" stroke="var(--accent)" stroke-width="2"
    stroke-linejoin="round" stroke-linecap="round"/>`;

  const dot = `<circle cx="${points[n - 1][0]}" cy="${points[n - 1][1]}" r="4"
    fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/>`;

  // Hit targets are full-height columns, so you never have to land on the line itself.
  const hits = points.map(([x], i) => `<rect class="hit" data-i="${i}"
    x="${x - (W / n) / 2}" y="${PAD.top}" width="${W / n}"
    height="${H - PAD.top - PAD.bottom}" fill="transparent"/>`).join("");

  const change = n > 1 ? PHRASE[key](delta, improving) : null;
  return `
    <section class="chart" data-key="${key}">
      <header>
        <b>${spec.format(last)}</b>
        <span class="name">${spec.label}</span>
        <span class="delta ${improving ? "up" : "down"}">
          ${change ? `${change} than your first session` : "your first session"}
        </span>
      </header>
      <p class="verdict ${state.state}">${state.text}</p>
      <div class="plot">
      <svg viewBox="0 0 ${W} ${H}" role="img" preserveAspectRatio="xMidYMid meet"
           aria-label="${spec.label} across ${n} sessions, currently ${spec.format(last)}">
        ${ticks}${band}${line}${dot}
        <line class="cross" y1="${PAD.top}" y2="${H - PAD.bottom}" stroke="var(--muted)"
              stroke-width="1" style="display:none"/>
        ${hits}
        <text x="${PAD.left}" y="${H - 8}" class="tick">${label(rows[0])}</text>
        <text x="${W - PAD.right}" y="${H - 8}" class="tick" text-anchor="end">
          ${label(rows[n - 1])}</text>
      </svg>
      <div class="tip" hidden></div>
      </div>
    </section>`;
}

/** Several sessions in one day are common, so fall back to the time when dates repeat. */
function shortener(rows) {
  const days = new Set(rows.map((r) => (r.started_at || "").slice(0, 10)));
  const sameDay = days.size < rows.length;
  return (row) => {
    const stamp = row?.started_at || "";
    return sameDay ? stamp.slice(11, 16) : stamp.slice(5, 10).replace("-", "/");
  };
}

export function trend(target, rows) {
  if (!rows.length) {
    target.innerHTML = `<p class="foot">No sessions yet.</p>`;
    return;
  }
  target.innerHTML = `
    <p class="foot band-key"><span class="swatch"></span> the shaded band is the target</p>
    ${Object.keys(SERIES).map((key) => chart(key, rows)).join("")}
    <details class="table-view">
      <summary>See the numbers</summary>
      <div class="scroll">
        <table>
          <thead><tr><th>session</th><th>answers</th>
            ${Object.values(SERIES).map((s) => `<th>${s.label}</th>`).join("")}</tr></thead>
          <tbody>${[...rows].reverse().map((r) => `<tr>
            <td>${(r.started_at || "").slice(0, 16)}</td><td>${r.answers ?? ""}</td>
            ${Object.entries(SERIES).map(([k, s]) => `<td>${s.format(r[k] ?? 0)}</td>`).join("")}
          </tr>`).join("")}</tbody>
        </table>
      </div>
    </details>`;

  target.querySelectorAll(".chart").forEach((node) => attach(node, rows));
}

/** Crosshair and tooltip. A chart in a browser should answer "what was that point?". */
function attach(node, rows) {
  const key = node.dataset.key;
  const spec = SERIES[key];
  const svg = node.querySelector("svg");
  const cross = node.querySelector(".cross");
  const tip = node.querySelector(".tip");

  const show = (i) => {
    const row = rows[i];
    const x = scale(spec, rows.map((r) => r[key] ?? 0)).x(i, rows.length);
    cross.setAttribute("x1", x);
    cross.setAttribute("x2", x);
    cross.style.display = "";
    tip.hidden = false;
    tip.style.left = `${Math.min(88, Math.max(12, (x / W) * 100))}%`;
    tip.innerHTML = `<b>${spec.format(row[key] ?? 0)}</b>
      ${(row.started_at || "").slice(0, 10)} · ${row.mode ?? ""}`;
  };
  const hide = () => { cross.style.display = "none"; tip.hidden = true; };

  svg.querySelectorAll(".hit").forEach((hit) => {
    hit.addEventListener("mouseenter", () => show(Number(hit.dataset.i)));
    hit.addEventListener("focus", () => show(Number(hit.dataset.i)));
  });
  svg.addEventListener("mouseleave", hide);
  svg.addEventListener("blur", hide, true);
}
