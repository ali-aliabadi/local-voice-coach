// Two steps, two routes: /modes then /models. Separate pages so each choice can be
// linked to, reloaded, and backed out of.

import { get } from "../form.js";
import { go } from "../router.js";

export const modes = {
  async render(root) {
    const [list, { isSet }] = await Promise.all([get("/api/modes"), get("/api/profile")]);
    root.innerHTML = `
      <h1>What are we practising?</h1>
      ${isSet ? "" : `<p class="callout">Fill in <a href="/profile">your profile</a> first
        so it knows what to call you, your first language, and — for the interview modes —
        your level and what you work on.</p>`}
      <div class="cards">
        ${list.map((m) => `<a class="card" href="/models?mode=${m.name}">
          <b>${m.name}</b><span>${m.help}</span></a>`).join("")}
      </div>`;
  },
};

export const models = {
  async render(root, _params, query) {
    const mode = query.get("mode") || "talk";
    const list = await get("/api/modes");
    const chosen = list.find((m) => m.name === mode) || list[0];
    const data = await get(`/api/backends?role=${chosen.endpoint}`);

    root.innerHTML = `
      <p class="crumbs"><a href="/modes">mode</a> › <b>${mode}</b></p>
      <h1>Which model plays the ${chosen.partner}?</h1>
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

    root.querySelectorAll(".pick").forEach((button) =>
      button.addEventListener("click", () =>
        go(`/practice?mode=${mode}&backend=${button.dataset.key}`)));
  },
};
