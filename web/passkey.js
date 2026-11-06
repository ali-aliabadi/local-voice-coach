// WebAuthn between the browser and the server's JSON. The options arrive with their byte
// fields as base64url text and the credential goes back the same way. The browser's own
// parse...FromJSON and toJSON() would do this, but Safari only gained them in 2025, and
// a phone a year behind is still the phone someone practises on.
//
// Safari asks for a passkey only straight from a tap: a fetch between the tap and
// navigator.credentials made an iPhone refuse with no prompt at all. So the server's
// options are fetched before the tap (`prepare`), and the tap calls the browser first,
// before anything else is awaited.

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

// The server's side of one ceremony, ready before the tap: "register" with an invite
// token, or "login". Good for one try, for a few minutes (login.CEREMONY_SECONDS).
export async function prepare(kind, token) {
  const { ticket, options } = await call(`/api/passkey/${kind}/options`, token ? { token } : {});
  const publicKey = kind === "register"
    ? {
      ...options,
      challenge: toBytes(options.challenge),
      user: { ...options.user, id: toBytes(options.user.id) },
      excludeCredentials: ids(options.excludeCredentials),
    }
    : {
      ...options,
      challenge: toBytes(options.challenge),
      allowCredentials: ids(options.allowCredentials),
    };
  return { kind, ticket, publicKey };
}

// Make a passkey on this device from an invite link. Signs you in.
export async function create(prepared, token) {
  const made = await navigator.credentials.create({ publicKey: prepared.publicKey });
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
  return call("/api/passkey/register", { ticket: prepared.ticket, token, credential });
}

// Sign in with whichever passkey this device holds for the site.
export async function signIn(prepared) {
  const got = await navigator.credentials.get({ publicKey: prepared.publicKey });
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
  return call("/api/passkey/login", { ticket: prepared.ticket, credential });
}

export const signOut = () => call("/api/passkey/logout");
