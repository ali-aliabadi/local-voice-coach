// Who the partner thinks it is talking to. This is what makes it a trainer rather than a
// stranger asking generic questions.

import { escape, field, get, post, values } from "../form.js";

export async function render(root) {
  const { fields } = await get("/api/profile");
  root.innerHTML = `
    <h1>Your profile</h1>
    <p class="foot lead">Every mode knows your name and first language. The interview modes
    also push on what you want to get better at. Nothing is ever repeated back to you — except your resume and the job posting, which the interviewer has read before
    you walk in and asks about, the way a real one does.</p>
    <form id="profile-form">${fields.map(field).join("")}</form>
    <div class="row">
      <button class="primary" id="save">Save</button>
      <span class="saved" id="saved" hidden>saved</span>
    </div>`;

  root.querySelectorAll("input[type=file][data-into]").forEach((input) =>
    input.addEventListener("change", () => upload(root, input)));

  root.querySelector("#save").addEventListener("click", async (event) => {
    event.preventDefault();
    await post("/api/profile", values(root.querySelector("#profile-form")));
    const saved = root.querySelector("#saved");
    saved.hidden = false;
    setTimeout(() => { saved.hidden = true; }, 2500);
  });
}

/** Read a file into its box through the server, to check before saving. */
async function upload(root, input) {
  const [file] = input.files;
  if (!file) return;
  const box = root.querySelector(`#${input.dataset.into}`);
  const note = root.querySelector(`#${input.dataset.into}-note`);
  note.textContent = `Reading ${file.name}…`;
  note.classList.remove("bad");
  const response = await fetch(`/api/extract?name=${encodeURIComponent(file.name)}`,
    { method: "POST", body: file });
  const result = await response.json().catch(() => ({ error: "The server did not answer." }));
  if (result.error) {
    note.textContent = result.error;
    note.classList.add("bad");
    return;
  }
  box.value = result.text;
  const words = result.text.split(/\s+/).filter(Boolean).length;
  note.innerHTML = `Read ${words} words from ${escape(file.name)}. Check it, then
    <b>Save</b>.`;
}
