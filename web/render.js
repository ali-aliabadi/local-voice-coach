// Drawing. Hand-rolled SVG on purpose: a chart library is 200KB for one trend line, and
// a CDN would break the promise that this works offline.

const escape = (text) =>
  text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

export function metrics(target, m) {
  const cells = [
    [m.wpm, 'words / min'],
    [m.fillers, m.fillers === 1 ? 'filler' : 'fillers'],
    [m.pauses, m.pauses === 1 ? 'pause' : 'pauses'],
    [`${m.lead_in}s`, 'before you spoke'],
  ];
  target.innerHTML = cells
    .map(([value, label]) => `<div class="metric"><b>${value}</b><span>${label}</span></div>`)
    .join('');
}

/** The answer as text, with every filler word marked. You see them, not a count. */
export function transcript(target, words, fallback) {
  if (!words?.length) {
    target.textContent = fallback;
    return;
  }
  target.innerHTML = words
    .map((w) =>
      w.filler
        ? `<span class="filler" title="filler">${escape(w.word)}</span>`
        : escape(w.word))
    .join(' ');
}

/**
 * The answer as a strip: speech in the accent colour, silences as gaps.
 * A two-second hole is visceral in a way `longest_pause: 2.0` never is.
 */
export function timeline(target, words) {
  if (!words?.length) { target.innerHTML = ''; return; }
  const end = words[words.length - 1].end || 1;
  const W = 640, H = 34;
  const x = (t) => (t / end) * W;

  const gaps = words
    .filter((w) => w.pause > 0)
    .map((w) => {
      const from = x(w.start - w.pause);
      return `<rect x="${from.toFixed(1)}" y="2" width="${(x(w.start) - from).toFixed(1)}"
        height="${H - 4}" rx="3" fill="color-mix(in srgb, var(--warn) 15%, transparent)"/>`;
    });

  const lead = words[0].start > 0
    ? `<rect x="0" y="2" width="${x(words[0].start).toFixed(1)}" height="${H - 4}" rx="3"
        fill="color-mix(in srgb, var(--muted) 18%, transparent)"/>`
    : '';

  const speech = words.map((w) => {
    const left = x(w.start);
    const width = Math.max(1.5, x(w.end) - left);
    const fill = w.filler ? 'var(--warn)' : 'var(--accent)';
    return `<rect x="${left.toFixed(1)}" y="11" width="${width.toFixed(1)}" height="12"
      rx="2.5" fill="${fill}"/>`;
  });

  target.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px;width:100%"
         role="img" aria-label="Your answer over time. Gaps are silences.">
      ${lead}${gaps.join('')}${speech.join('')}
    </svg>
    <p class="foot">grey = before you started &middot; pale red = a pause &middot;
       red = a filler word</p>`;
}

function sparkline(rows, key, invert) {
  const values = rows.map((r) => r[key] ?? 0);
  const W = 220, H = 42;
  const low = Math.min(...values), high = Math.max(...values);
  const span = high - low || 1;
  const points = values.map((v, i) => {
    const px = values.length === 1 ? W / 2 : (i / (values.length - 1)) * W;
    return `${px.toFixed(1)},${(H - 4 - ((v - low) / span) * (H - 12)).toFixed(1)}`;
  });
  const first = values[0], last = values[values.length - 1];
  const better = invert ? last < first : last > first;
  const delta = (last - first).toFixed(key === 'wpm' ? 0 : 1);
  const colour = values.length < 2 ? 'var(--muted)' : better ? 'var(--accent)' : 'var(--warn)';
  return { points: points.join(' '), colour, delta, last, W, H };
}

/** Four small multiples. Small numbers, honest direction, no dashboard theatre. */
export function trend(target, rows) {
  if (!rows.length) {
    target.innerHTML = '<p class="foot">No sessions yet. Practise once and this fills in.</p>';
    return;
  }
  const series = [
    ['wpm', 'words / min', false],
    ['fillers', 'fillers per answer', true],
    ['pauses', 'pauses per answer', true],
    ['lead_in', 'seconds before speaking', true],
  ];
  target.innerHTML = series.map(([key, label, invert]) => {
    const s = sparkline(rows, key, invert);
    const sign = s.delta > 0 ? '+' : '';
    return `<div class="metric" style="margin-bottom:2rem">
      <b>${Number(s.last).toFixed(key === 'wpm' ? 0 : 1)}</b>
      <span>${label} &middot; ${rows.length > 1 ? `${sign}${s.delta} since your first session` : 'first session'}</span>
      <svg viewBox="0 0 ${s.W} ${s.H}" style="height:${s.H}px;width:100%;margin-top:.5rem">
        <polyline points="${s.points}" fill="none" stroke="${s.colour}"
                  stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      </svg>
    </div>`;
  }).join('');
}
