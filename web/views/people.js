// Who uses this app. Everyone sees themselves and can make a link for another device of
// their own; an admin also sees everyone, invites someone new, and can lock someone out.
// A link goes to Telegram when that person has a Relay name, and is shown here either way.

import { escape, get } from "../form.js";
import { signOut } from "../passkey.js";

async function send(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `The server said ${response.status}.`);
  return data;
}

const seen = (p) => (p.passkeys
  ? `${p.passkeys} passkey${p.passkeys === 1 ? "" : "s"}${p.last_seen ? ` · last in ${p.last_seen.slice(0, 10)}` : ""}`
  : p.pending ? "invited, no passkey yet" : "no passkey");

function row(p, me) {
  const self = p.id === me.id;
  return `<li class="person">
    <div><strong>${escape(p.name)}</strong>${self ? " <small>(you)</small>" : ""}
      ${p.admin ? ' <small class="tag">admin</small>' : ""}
      <small class="foot">${seen(p)}${p.relay ? ` · Telegram ${escape(p.relay)}` : ""}</small></div>
    <div class="row">
      <button class="link" data-link="${p.id}">${self ? "add another device" : "new link"}</button>
      ${me.admin && !self ? `<button class="link warn" data-revoke="${p.id}">lock out</button>` : ""}
    </div>
  </li>`;
}

function shown(root, made, who) {
  const box = root.querySelector("#made");
  box.hidden = false;
  box.innerHTML = `<p>${made.sent
    ? `Sent to ${escape(who)}'s Telegram. You can also pass it on yourself:`
    : `Send this to ${escape(who)} any way you like. It works once:`}</p>
    <input readonly class="made" value="${escape(made.link)}" aria-label="Sign-in link">
    <button class="link" id="copy">copy</button>`;
  root.querySelector("#copy").onclick = async () => {
    await navigator.clipboard?.writeText(made.link).catch(() => {});
    root.querySelector("#copy").textContent = "copied";
  };
}

export async function render(root) {
  const data = await get("/api/people");
  const { me } = data;
  root.innerHTML = `
    <h1>People</h1>
    ${data.required ? "" : `<p class="foot">Only this machine can reach the app, so nobody
      signs in. Set ALLOWED_HOSTS to serve it to your phone, and passkeys take over.</p>`}
    <ul class="people">${data.people.map((p) => row(p, me)).join("")}</ul>
    <div id="made" class="made-box" hidden></div>
    <p id="said" class="foot warn" role="status"></p>
    ${me.admin ? `<h2>Invite someone</h2>
      <form id="invite" class="row">
        <label><span>Name</span><input name="name" required maxlength="60" autocomplete="off"></label>
        <label><span>Relay username${data.telegram ? "" : " (Relay is off)"}</span>
          <input name="relay" autocomplete="off" placeholder="optional"></label>
        <button class="primary">Make a link</button>
      </form>
      <p class="foot">They open the link on their phone and make a passkey. It lasts two
        days. A Relay username sends it to their Telegram, and later their own reports.</p>` : ""}
    ${data.required ? `<hr><button class="danger" id="out">Sign out on this device</button>` : ""}`;

  const said = (text) => { root.querySelector("#said").textContent = text; };
  const name = (id) => data.people.find((p) => p.id === Number(id))?.name || "them";

  root.querySelectorAll("[data-link]").forEach((button) => {
    button.onclick = async () => {
      try { shown(root, await send(`/api/people/${button.dataset.link}/link`), name(button.dataset.link)); }
      catch (error) { said(error.message); }
    };
  });
  root.querySelectorAll("[data-revoke]").forEach((button) => {
    button.onclick = async () => {
      const who = name(button.dataset.revoke);
      if (!confirm(`Lock ${who} out? Their passkeys stop working and every device of theirs is signed out. Their practice history stays.`)) return;
      try { await send(`/api/people/${button.dataset.revoke}/revoke`); await render(root); }
      catch (error) { said(error.message); }
    };
  });
  root.querySelector("#invite")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.target));
    try {
      const made = await send("/api/people", form);
      await render(root);
      shown(root, made, form.name);
    } catch (error) { said(error.message); }
  });
  root.querySelector("#out")?.addEventListener("click", async () => {
    await signOut().catch(() => {});
    location.assign("/login");
  });
}
