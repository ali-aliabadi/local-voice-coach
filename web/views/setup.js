// Two steps, two routes: /modes then /models. Separate pages so each choice can be
// linked to, reloaded, and backed out of.

import { GOALS, keepGoal, lastGoal } from "../clock.js";
import { get } from "../form.js";
import { go } from "../router.js";

/** Open modes are links, the starter mode the biggest; a locked one says when it opens. */
const card = (m) => (m.state === "open"
  ? `<a class="card${m.unlock === 0 ? " hero" : ""}" href="/models?mode=${m.name}">
      <b>${m.name}</b><span>${m.help}</span></a>`
  : `<div class="card locked" aria-disabled="true">
      <b>${m.name}<span class="tag">after ${m.left} more session${m.left === 1 ? "" : "s"}</span></b>
      <span>${m.help}</span></div>`);

export const modes = {
  async render(root) {
    const [list, { isSet, resume }] = await Promise.all([get("/api/modes"), get("/api/profile")]);
    const interviews = list.some((m) => m.interview && m.state === "open");
    root.innerHTML = `
      <h1>What are we practising?</h1>
      ${isSet ? "" : `<p class="callout">Fill in <a href="/profile">your profile</a> first
        so it knows what to call you, your first language, and — for the interview modes —
        your level, what you work on, and your resume.</p>`}
      ${isSet && !resume && interviews ? `<p class="callout">The interview modes read your
        resume first, like a real interviewer. Add it — and the job posting, if you have
        one — in <a href="/profile">your profile</a>.</p>` : ""}
      <div class="cards">${list.filter((m) => m.state !== "hidden").map(card).join("")}</div>
      ${list.some((m) => m.state === "hidden") ? `<p class="foot">Start with a conversation.
        More modes open as you practise.</p>` : ""}`;
  },
};

const QUIETS = [1.5, 2, 2.5, 3, 4, 5];  // seconds; Settings' own value joins if not here

/** Chips for one choice; `aria-pressed` marks the one taken. */
const chips = (name, options, chosen) => options.map(([value, label]) =>
  `<button class="chip-button" data-${name}="${value}"
    aria-pressed="${String(value) === String(chosen)}">${label}</button>`).join("");

/** How this session listens, prefilled from Settings. A choice here lasts one session:
 * it rides in the link to /practice and is never saved, so Settings keeps the default. */
function talkingChoice(root, form) {
  const value = (key) => form.find((f) => f.key === key)?.value;
  const chosen = { talking: value("talking") || "space", silence: Number(value("hands_free_silence")) || 3 };
  const quiets = [...new Set([...QUIETS, chosen.silence])].sort((a, b) => a - b);
  const draw = () => {
    root.querySelector("#talking").innerHTML = `
      <fieldset class="goals"><legend>Talking, this session</legend>
        ${chips("talking", [["space", "tap to talk"], ["hybrid", "hands-free"]], chosen.talking)}
      </fieldset>
      ${chosen.talking === "hybrid" ? `<fieldset class="goals">
        <legend>Hands-free: quiet before your answer ends</legend>
        ${chips("silence", quiets.map((q) => [q, `${q}s`]), chosen.silence)}
      </fieldset>` : ""}`;
    root.querySelectorAll("[data-talking]").forEach((b) => b.addEventListener("click", () => {
      chosen.talking = b.dataset.talking;
      draw();
    }));
    root.querySelectorAll("[data-silence]").forEach((b) => b.addEventListener("click", () => {
      chosen.silence = Number(b.dataset.silence);
      draw();
    }));
  };
  draw();
  return () => `&talking=${chosen.talking}&silence=${chosen.silence}`;
}

export const models = {
  async render(root, _params, query) {
    const mode = query.get("mode") || "talk";
    const list = await get("/api/modes");
    const chosen = list.find((m) => m.name === mode) || list[0];
    const [data, form] = await Promise.all([
      get(`/api/backends?role=${chosen.endpoint}`), get("/api/settings")]);

    root.innerHTML = `
      <p class="crumbs"><a href="/modes">mode</a> › <b>${mode}</b></p>
      <h1>Which model plays the ${chosen.partner}?</h1>
      <fieldset class="goals"><legend>Today's goal</legend>
        ${GOALS.map((g) => `<button class="chip-button" data-goal="${g}"
          aria-pressed="${g === lastGoal()}">${g ? `${g} min` : "no goal"}</button>`).join("")}
      </fieldset>
      <div id="talking"></div>
      <div class="table">
        ${data.backends.map((b) => {
          const yours = b.samples
            ? `yours ${(b.measured_ms / 1000).toFixed(1)}s (n=${b.samples})`
            : b.latency;
          return `<button class="pick" data-key="${b.key}" ${b.blocked ? "disabled" : ""}>
            <b>${b.label}${b.free ? '<span class="tag free">free</span>'
                                  : `<span class="tag">${b.cost}</span>`}</b>
            <span class="cost">${yours}</span>
            <span class="meta">${b.blocked ? `unavailable — ${b.blocked}` : b.note}</span>
          </button>`;
        }).join("")}
      </div>
      <p class="foot">${data.available
        ? `<b>Latency</b> is published or estimated. <b>Yours</b> is measured from your own
           past sessions — trust that one. Greyed rows are unreachable right now.`
        : `Nothing reachable: no internet, and LM Studio is not serving a usable model.
           Add an API key in <a href="/settings">settings</a>, or start LM Studio.`}</p>`;

    const talking = talkingChoice(root, form);
    root.querySelectorAll("[data-goal]").forEach((button) =>
      button.addEventListener("click", () => {
        keepGoal(Number(button.dataset.goal));
        root.querySelectorAll("[data-goal]").forEach((b) =>
          b.setAttribute("aria-pressed", String(b === button)));
      }));
    root.querySelectorAll(".pick").forEach((button) =>
      button.addEventListener("click", () =>
        go(`/practice?mode=${mode}&backend=${button.dataset.key}&goal=${lastGoal()}${talking()}`)));
  },
};
