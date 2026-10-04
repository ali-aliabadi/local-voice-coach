import { field, get, post, values } from "../form.js";
import { CHOICES, current, set } from "../theme.js";

const GROUPS = ["Backends", "Practice", "Scoring", "Model", "Coach", "Telegram", "Prompts"];

const INTRO = {
  Prompts: "Change how each mode behaves: steer the talk partner toward topics you care "
    + "about, or aim the interviewer at a company, role or seniority. "
    + "Clear a box to restore the built-in prompt.",
};

export async function render(root) {
  const items = await get("/api/settings");
  root.innerHTML = `
    <h1>Settings</h1>
    <fieldset><legend>Appearance</legend>
      <label for="theme"><span>Theme</span>
        <select id="theme">
          ${CHOICES.map((c) => `<option value="${c}"${c === current() ? " selected" : ""}>
            ${c === "auto" ? "follow my system" : c}</option>`).join("")}
        </select>
        <small>Takes effect immediately.</small>
      </label>
    </fieldset>
    <form id="settings-form">
      ${GROUPS.map((group) => {
        const rows = items.filter((i) => i.group === group);
        if (!rows.length) return "";
        const intro = INTRO[group] ? `<p class="foot">${INTRO[group]}</p>` : "";
        return `<fieldset><legend>${group}</legend>${intro}${rows.map(field).join("")}</fieldset>`;
      }).join("")}
    </form>
    <div class="row">
      <button class="primary" id="save">Save</button>
      <span class="saved" id="saved" hidden>saved</span>
    </div>
    <hr>
    <h2>Your data</h2>
    <p class="foot">Everything is on this machine. Nothing is uploaded.</p>
    <button id="forget" class="danger">Delete every session and recording</button>`;

  root.querySelector("#theme").addEventListener("change", (event) => set(event.target.value));

  root.querySelector("#save").addEventListener("click", async (event) => {
    event.preventDefault();
    await post("/api/settings", values(root.querySelector("#settings-form")));
    await render(root);                       // re-read, so you see what actually stuck
    const saved = root.querySelector("#saved");
    saved.hidden = false;
    setTimeout(() => { saved.hidden = true; }, 2500);
  });

  root.querySelector("#forget").addEventListener("click", async (event) => {
    if (!confirm("Delete every session, metric and recording? This cannot be undone.")) return;
    await fetch("/api/forget", { method: "POST" });
    event.target.textContent = "Deleted.";
  });
}
