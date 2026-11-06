// WebAuthn between the browser and the server's JSON. The options arrive with their byte
// fields as base64url text and the credential goes back the same way. The browser's own
// parse...FromJSON and toJSON() would do this, but Safari only gained them in 2025, and
// a phone a year behind is still the phone someone practises on.

const toBytes = (text) => {
  const base64 = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64 + "=".repeat((4 - (base64.length % 4)) % 4));
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
};

const toText = (buffer) => btoa(String.fromCharCode(...new Uint8Array(buffer)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

const ids = (list) => (list || []).map((c) => ({ ...c, id: toBytes(c.id) }));

async function call(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `The server said ${response.status}.`);
  return data;
}

export const supported = () => Boolean(window.PublicKeyCredential && navigator.credentials);

// Make a passkey on this device from an invite link. Signs you in.
export async function create(token) {
  const { ticket, options } = await call("/api/passkey/register/options", { token });
  const made = await navigator.credentials.create({
    publicKey: {
      ...options,
      challenge: toBytes(options.challenge),
      user: { ...options.user, id: toBytes(options.user.id) },
      excludeCredentials: ids(options.excludeCredentials),
    },
  });
  const credential = {
    id: made.id,
    rawId: toText(made.rawId),
    type: made.type,
    response: {
      clientDataJSON: toText(made.response.clientDataJSON),
      attestationObject: toText(made.response.attestationObject),
      transports: made.response.getTransports?.() || [],
    },
    clientExtensionResults: made.getClientExtensionResults(),
  };
  return call("/api/passkey/register", { ticket, token, credential });
}

// Sign in with whichever passkey this device holds for the site.
export async function signIn() {
  const { ticket, options } = await call("/api/passkey/login/options");
  const got = await navigator.credentials.get({
    publicKey: {
      ...options,
      challenge: toBytes(options.challenge),
      allowCredentials: ids(options.allowCredentials),
    },
  });
  const credential = {
    id: got.id,
    rawId: toText(got.rawId),
    type: got.type,
    response: {
      clientDataJSON: toText(got.response.clientDataJSON),
      authenticatorData: toText(got.response.authenticatorData),
      signature: toText(got.response.signature),
      userHandle: got.response.userHandle ? toText(got.response.userHandle) : null,
    },
    clientExtensionResults: got.getClientExtensionResults(),
  };
  return call("/api/passkey/login", { ticket, credential });
}

export const signOut = () => call("/api/passkey/logout");
