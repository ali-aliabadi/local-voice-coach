// The server's Gemini keys and Telegram connection, on the Settings page, for an admin.
// The server never sends a key back, only its last four characters, and changes nothing
// until the admin has confirmed with their passkey in the last ten minutes (keyring.py).

import { escape } from "./form.js";
import { prepare, signIn, supported } from "./passkey.js";

const FRESH_MS = 4 * 60 * 1000;  // ceremony options are good for five (see login.js)
let refresh = null;

async function call(url, body) {
  const response = await fetch(url, body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `The server said ${response.status}.`);
  return data;
}

function telegram({ missing, problem }) {
  if (missing.length) return `Off. Still needed: ${missing.join(", ")}.`;
  if (problem) return `On, but it cannot send yet: ${problem}.`;
  return "On. Reports and sign-in links go to Telegram.";
}

function key(k, locked) {
  const end = k.from === "env"
    ? '<small class="foot">set in .env</small>'
    : `<button class="link warn" data-remove="${k.id}"${locked ? " disabled" : ""}>remove</button>`;
  return `<li><code>${escape(k.shown)}</code>${end}</li>`;
}

function setting(r, locked) {
  const fixed = r.from === "env";
  const hint = r.secret && r.value ? ` placeholder="stored, ends ${escape(r.value.slice(1))}"` : "";
  return `<label><span>${escape(r.label)}</span>
    <input name="${r.name}" type="${r.secret ? "password" : "text"}" autocomplete="off"
      value="${r.secret ? "" : escape(r.value)}"${hint}${locked || fixed ? " disabled" : ""}>
    <small>${escape(r.help)}${fixed ? " Set in .env, which wins." : ""}
      ${r.secret && r.value && !fixed ? " Leave blank to keep it." : ""}</small></label>`;
}

function draw(box, data) {
  clearTimeout(refresh);
  const locked = !data.fresh;
  const off = locked ? " disabled" : "";
  box.innerHTML = `
    <fieldset><legend>Keys and Telegram</legend>
      ${locked ? `<p class="foot">Changing these asks for your passkey again, so a phone
        left signed in is not enough.</p>
        <button class="primary" id="unlock" disabled>Confirm with your passkey</button>` : ""}
      <p id="said" class="foot warn" role="status"></p>
      <h3>Gemini keys</h3>
      <p class="foot">Free at aistudio.google.com/apikey. Each key has its own free quota:
        when one is refused, the next one answers.</p>
      <ul class="keys">${data.keys.map((k) => key(k, locked)).join("")
        || '<li class="foot">None yet. Practice needs at least one.</li>'}</ul>
      <form id="add-key" class="row">
        <label><span>Add a key</span>
          <input name="key" type="password" autocomplete="off"${off}></label>
        <button class="primary"${off}>Add</button>
      </form>
      <h3>Telegram, through Relay</h3>
      <p class="foot">${escape(telegram(data.telegram))}</p>
      <form id="relay">
        ${data.relay.map((r) => setting(r, locked)).join("")}
        <button class="primary"${off}>Save Telegram</button>
      </form>
    </fieldset>`;

  const said = (text) => { box.querySelector("#said").textContent = text; };
  // Whatever happens is said where it can be seen. A refusal redraws first: once the
  // passkey's ten minutes ran out, the form looked open and Save failed out of sight.
  const act = async (url, body, done) => {
    try {
      const data = await call(url, body);
      draw(box, data);
      box.querySelector("#said").textContent = done(data);
    } catch (error) {
      await keyring(box);
      box.querySelector("#said").textContent = error.message;
    }
    box.querySelector("#said").scrollIntoView({ block: "center", behavior: "smooth" });
  };

  box.querySelectorAll("[data-remove]").forEach((button) => {
    button.onclick = () => act(`/api/keyring/keys/${button.dataset.remove}/remove`, {}, () => "Key removed.");
  });
  box.querySelector("#add-key").onsubmit = (event) => {
    event.preventDefault();
    act("/api/keyring/keys", { key: event.target.key.value }, () => "Key added.");
  };
  box.querySelector("#relay").onsubmit = (event) => {
    event.preventDefault();
    const fields = [...event.target.querySelectorAll("input:not(:disabled)")];
    act("/api/keyring/relay", Object.fromEntries(fields.map((f) => [f.name, f.value])),
      (data) => `Saved. Telegram: ${telegram(data.telegram)}`);
  };
  if (locked) unlock(box, said);
}

// As on the sign-in page: the options are fetched before the tap, because Safari only
// shows the passkey prompt when it is asked straight from one.
async function unlock(box, said) {
  const button = box.querySelector("#unlock");
  if (!supported()) { said("This browser cannot use passkeys."); return; }
  let ready;
  try { ready = await prepare("confirm"); } catch (error) { said(error.message); return; }
  button.disabled = false;
  refresh = setTimeout(() => { if (box.isConnected) unlock(box, said); }, FRESH_MS);
  button.onclick = () => {
    button.disabled = true;
    clearTimeout(refresh);
    signIn(ready).then(
      () => keyring(box),
      (error) => {
        said(error.name === "NotAllowedError" ? "Cancelled." : error.message);
        unlock(box, said);
      },
    );
  };
}

// Draws into `box`, or hides it for someone who is not an admin.
export async function keyring(box) {
  try { draw(box, await call("/api/keyring")); } catch { box.hidden = true; }
}
