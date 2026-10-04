// Run: node tests/test_web.mjs
// Plain asserts, same as the Python tests. This exists because a chart bug shipped that
// every Python test passed straight through: SERIES.wpm.format returned a Number, and
// the review page called .replace on it.

import assert from "node:assert/strict";
import { MOVED, PHRASE, SERIES, moved, verdict } from "../web/chart.js";
import { mmss } from "../web/clock.js";

// ---- the session clock reads naturally past an hour ----
assert.equal(mmss(75), "01:15");
assert.equal(mmss(21331), "5:55:31");

// ---- every format returns a string, whatever the metric ----
for (const [key, spec] of Object.entries(SERIES)) {
  const out = spec.format(3.14159);
  assert.equal(typeof out, "string", `${key}.format must return a string, got ${typeof out}`);
  assert.equal(typeof spec.format(0), "string", `${key}.format(0)`);
}
assert.equal(SERIES.wpm.format(136.4), "136");
assert.equal(SERIES.lead_in.format(1.44), "1.4s");

// ---- verdicts: a number means nothing without one ----
assert.equal(verdict("wpm", 150).state, "good");          // inside 140-160
assert.equal(verdict("wpm", 118).state, "far");
assert.equal(verdict("fillers", 1.2).state, "good");      // inside 0-2
assert.equal(verdict("fillers", 2.6).state, "near");
assert.equal(verdict("fillers", 7).state, "far");
assert.equal(verdict("lead_in", 0.9).state, "good");
for (const key of Object.keys(SERIES)) {
  assert.ok(verdict(key, 0).text.length > 0, `${key} needs wording at zero`);
  assert.ok(verdict(key, 999).text.length > 0, `${key} needs wording off the scale`);
}

// ---- goal bands sit inside their domain, or the band draws outside the plot ----
for (const [key, spec] of Object.entries(SERIES)) {
  const [lo, hi] = spec.domain;
  const [glo, ghi] = spec.goal;
  assert.ok(glo >= lo && ghi <= hi, `${key} goal ${glo}-${ghi} escapes domain ${lo}-${hi}`);
  assert.ok(lo < hi, `${key} domain must ascend`);
}

// ---- "better" has to follow the metric, not the sign of the change ----
assert.equal(moved("fillers", 1.0, 3.0).better, true);    // fewer fillers is better
assert.equal(moved("fillers", 3.0, 1.0).better, false);
assert.equal(moved("wpm", 130, 110).better, true);        // faster is better
assert.equal(moved("wpm", 110, 130).better, false);
assert.equal(moved("lead_in", 1.0, 2.5).better, true);

// ---- noise must not be reported as change ----
assert.equal(moved("wpm", 118, 116), null, "2 wpm is noise");
assert.equal(moved("fillers", 3.0, 3.1), null, "0.1 fillers is noise");
assert.equal(moved("fillers", 3.0, null), null, "nothing to compare against");
for (const [key, threshold] of Object.entries(MOVED)) {
  assert.equal(moved(key, threshold * 0.9, 0), null, `${key} below threshold is noise`);
  assert.ok(moved(key, threshold * 1.1, 0), `${key} above threshold is real`);
}

// ---- the phrasing says the direction in words, never leaving it to an arrow ----
assert.equal(PHRASE.fillers(-1.9, true), "1.9 fewer fillers per 100 words");
assert.equal(PHRASE.fillers(1.9, false), "1.9 more fillers per 100 words");
assert.equal(PHRASE.pauses(-2, true), "2.0 fewer pauses a minute");
assert.equal(PHRASE.wpm(12.4, true), "12 wpm faster");
assert.equal(PHRASE.lead_in(-0.9, true), "0.9s quicker to start");
for (const [key, phrase] of Object.entries(PHRASE)) {
  for (const better of [true, false]) {
    const text = phrase(1.5, better);
    assert.ok(!/^-/.test(text), `${key} must not surface a minus sign: ${text}`);
    assert.ok(!text.includes("NaN"), `${key} produced NaN`);
  }
}

console.log("ok");
