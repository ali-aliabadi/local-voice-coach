// The sign-in page: the only page served before you have signed in. With ?invite= it
// makes a passkey on this device instead; either way you land where you were going.

import { create, signIn, supported } from "./passkey.js";
import { apply } from "./theme.js";

apply();
const $ = (selector) => document.querySelector(selector);
const query = new URLSearchParams(location.search);
const token = query.get("invite");
// Only a path on this site: a link must not be able to send you somewhere else.
const asked = query.get("next") || "/";
const next = asked.startsWith("/") && !asked.startsWith("//") ? asked : "/";

const say = (text, warn = false) => {
  $("#status").textContent = text;
  $("#status").classList.toggle("warn", warn);
};

function failed(error) {
  $("#go").disabled = false;
  // Closing the phone's own prompt is a choice, not a fault.
  if (error.name === "NotAllowedError") say("Cancelled. Try again when you are ready.");
  else if (error.name === "InvalidStateError") say("This device already has a passkey here. Sign in instead.", true);
  else say(error.message || String(error), true);
}

async function invited() {
  const response = await fetch(`/api/passkey/invite?token=${encodeURIComponent(token)}`);
  const data = await response.json().catch(() => ({}));
  $("#new").hidden = true;
  if (!response.ok) {
    $("#title").textContent = "This link has run out";
    $("#lead").textContent = data.error || "Ask for a new one.";
    $("#go").textContent = "Sign in with a passkey instead";
    $("#go").onclick = () => go(signIn);
    return;
  }
  $("#title").textContent = data.passkeys ? `Add this device, ${data.name}` : `Welcome, ${data.name}`;
  $("#lead").textContent = "Make a passkey on this device. Your phone keeps it, unlocked "
    + "by your face, fingerprint or screen lock, and this app only ever stores its public "
    + "half. No password to remember. The link works once.";
  $("#go").textContent = "Make a passkey";
  $("#go").onclick = () => go(() => create(token));
}

async function go(ceremony) {
  $("#go").disabled = true;
  say("Waiting for your device…");
  try {
    await ceremony();
    location.replace(token ? "/" : next);
  } catch (error) {
    failed(error);
  }
}

if (!supported()) {
  $("#go").disabled = true;
  say("This browser cannot use passkeys. Open the page in Safari or Chrome.", true);
} else if (token) {
  invited();
} else {
  $("#go").onclick = () => go(signIn);
}
