import { get } from "./form.js";
import { go, render, route } from "./router.js";
import { apply } from "./theme.js";
import * as history_ from "./views/history.js";
import * as jobs from "./views/jobs.js";
import * as practice from "./views/practice.js";
import * as profile from "./views/profile.js";
import * as progress from "./views/progress.js";
import * as settings from "./views/settings.js";
import * as setup from "./views/setup.js";
import * as today from "./views/today.js";

route("/modes", setup.modes);
route("/models", setup.models);
route("/practice", practice);
route("/history", history_.list);
route("/history/:id", history_.detail);
route("/progress", progress);
route("/jobs", jobs);
route("/profile", profile);
route("/settings", settings);
route("/today", today);

// "/" is wherever you should be: back into a session you were mid-way through after a
// reload, otherwise today's page.
route("/", {
  render: () => {
    const live = practice.resumable();
    go(live ? "/practice" : "/today", true);
  },
});

// What this machine can run, for choosing a local model: LM Studio's model must fit in it.
get("/api/machine").then((m) => {
  const gpu = !m.gpu ? "no GPU a model can use"
    : m.unified ? `${m.gpu.cores}-core GPU, sharing the RAM`
      : `${m.gpu.name}, ${m.gpu.gb} GB`;
  const fits = m.model_gb == null
    ? `LM Studio is on ${m.lm_studio}: model sizes not checked`
    : `local models up to ${m.model_gb} GB`;
  document.getElementById("machine").textContent =
    `${m.cpu} · ${m.cores} cores · ${m.ram_gb} GB RAM · ${gpu} · ${fits}`;
}).catch(() => {});

apply();
render();
