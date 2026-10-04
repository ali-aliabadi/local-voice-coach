// Who the partner thinks it is talking to. This is what makes it a trainer rather than a
// stranger asking generic questions.

import { field, get, post, values } from "../form.js";

export async function render(root) {
  const { fields } = await get("/api/profile");
  root.innerHTML = `
    <h1>Your profile</h1>
    <p class="foot lead">Every mode knows your name and first language. The interview modes
    also read the rest: they pitch questions at your level, dig into the stack you actually
    named, and push on what you said you want to improve. Nothing is ever repeated back
    to you.</p>
    <form id="profile-form">${fields.map(field).join("")}</form>
    <div class="row">
      <button class="primary" id="save">Save</button>
      <span class="saved" id="saved" hidden>saved</span>
    </div>`;

  root.querySelector("#save").addEventListener("click", async (event) => {
    event.preventDefault();
    await post("/api/profile", values(root.querySelector("#profile-form")));
    const saved = root.querySelector("#saved");
    saved.hidden = false;
    setTimeout(() => { saved.hidden = true; }, 2500);
  });
}
