// The sign-in page: the only page served before you have signed in. With ?invite= it
// makes a passkey on this device instead; either way you land where you were going.

import { create, prepare, signIn, supported } from "./passkey.js";
import { apply } from "./theme.js";

apply();
const $ = (selector) => document.querySelector(selector);
const query = new URLSearchParams(location.search);
const token = query.get("invite");
// Only a path on this site: a link must not be able to send you somewhere else.
const asked = query.get("next") || "/";
const next = asked.startsWith("/") && !asked.startsWith("//") ? asked : "/";
// The server's options are fetched ahead of the tap (see passkey.js), and fetched again
// before they expire: someone can sit on this page a while before tapping.
const FRESH_MS = 4 * 60 * 1000;

let kind = "login";
let ready = null;   // the prepared ceremony, once it has arrived
let refresh = null;

const say = (text, warn = false) => {
  $("#status").textContent = text;
  $("#status").classList.toggle("warn", warn);
};

function failed(error) {
  // Closing the phone's own prompt is a choice, not a fault.
  if (error.name === "NotAllowedError") say("Cancelled. Try again when you are ready.");
  else if (error.name === "InvalidStateError") say("This device already has a passkey here. Sign in instead.", true);
  else say(error.message || String(error), true);
}

async function load() {
  ready = null;
  clearTimeout(refresh);
  $("#go").disabled = true;
  try {
    ready = await prepare(kind, kind === "register" ? token : null);
    $("#go").disabled = false;
    refresh = setTimeout(load, FRESH_MS);
  } catch (error) {
    failed(error);
  }
}

function go() {
  if (!ready) return;
  const prepared = ready;
  ready = null;  // a ticket is good for one try
  $("#go").disabled = true;
  say("Waiting for your device…");
  // The browser is asked first, inside the tap, before anything is awaited.
  const ceremony = kind === "register" ? create(prepared, token) : signIn(prepared);
  ceremony.then(
    () => location.replace(token ? "/" : next),
    (error) => { failed(error); load(); },
  );
}

async function invited() {
  const response = await fetch(`/api/passkey/invite?token=${encodeURIComponent(token)}`);
  const data = await response.json().catch(() => ({}));
  $("#new").hidden = true;
  if (!response.ok) {
    $("#title").textContent = "This link has run out";
    $("#lead").textContent = data.error || "Ask for a new one.";
    $("#go").textContent = "Sign in with a passkey instead";
    return load();
  }
  $("#title").textContent = data.passkeys ? `Add this device, ${data.name}` : `Welcome, ${data.name}`;
  $("#lead").textContent = "Make a passkey on this device. Your phone keeps it, unlocked "
    + "by your face, fingerprint or screen lock, and this app only ever stores its public "
    + "half. No password to remember. The link works once.";
  $("#go").textContent = "Make a passkey";
  kind = "register";
  return load();
}

$("#go").onclick = go;
if (!supported()) {
  $("#go").disabled = true;
  say("This browser cannot use passkeys. Open the page in Safari or Chrome.", true);
} else if (token) {
  invited();
} else {
  load();
}
