import { go, render, route } from "./router.js";
import { apply } from "./theme.js";
import * as history_ from "./views/history.js";
import * as practice from "./views/practice.js";
import * as profile from "./views/profile.js";
import * as progress from "./views/progress.js";
import * as settings from "./views/settings.js";
import * as setup from "./views/setup.js";

route("/modes", setup.modes);
route("/models", setup.models);
route("/practice", practice);
route("/history", history_.list);
route("/history/:id", history_.detail);
route("/progress", progress);
route("/profile", profile);
route("/settings", settings);

// "/" is wherever you should be: back into a session you were mid-way through after a
// reload, otherwise the mode picker.
route("/", {
  render: () => {
    const live = practice.resumable();
    go(live ? "/practice" : "/modes", true);
  },
});

apply();
render();
