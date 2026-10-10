"""Relay: notifications to your phone through Telegram. Optional, and off unless set up.

Relay is a small notification gateway: an app posts a message, Relay formats it for
Telegram, delivers it and retries. Set these in .env (never in Settings - the key is a
secret and is read from the environment only):

    RELAY_URL      Relay's base URL, e.g. https://relay.example.com
    RELAY_API_KEY  this app's key (rk_...), created by the Relay admin
    RELAY_APP      this app's name as Relay records it, e.g. voice-coach
    RELAY_USER     who this app sends to: your recipient's username. Relay has no default
                   recipient, so neither does this

What leaves: numbers, a chart, an interview's rating and hire decision, and - if you
allow it - the coach's lessons. Never audio, never whole transcripts. Message ids are logged; contents and the key never are.
"""

import asyncio
import base64
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from . import store


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def recipient() -> str:
    """Who this app sends to. Relay's skill dropped the fallback to "admin": reports went
    to whoever runs Relay, not to the person practising."""
    return _env("RELAY_USER")


def missing() -> list[str]:
    """What keeps Relay off: a variable unset, or a URL that is not http(s)."""
    needed = ("RELAY_URL", "RELAY_API_KEY", "RELAY_APP", "RELAY_USER")
    gaps = [name for name in needed if not _env(name)]
    if _env("RELAY_URL") and not _env("RELAY_URL").startswith(("http://", "https://")):
        gaps.append("RELAY_URL starting with https://")
    return gaps


def enabled() -> bool:
    return not missing()


def status() -> str:
    """A line for the server's start. Off used to be silent, which looks like a Relay that
    is set up and never sends."""
    if missing():
        return f"telegram: off - not set: {', '.join(missing())}"
    return f"telegram: on, as {_env('RELAY_APP')} to {recipient()}"


# What the check at the start found wrong; "" when it passed or has not run.
problem = ""
# The start waits for the check, so the header never says "on" for a Relay that does not
# work; this long at most, for a network that swallows the request.
CHECK_SECONDS = 5


def check() -> str:
    """Relay's own check, sending nothing: the URL and the key work, and the recipient
    exists and has Telegram linked. What is wrong, or "" when nothing is."""
    try:
        found = _call("GET", "/v1/recipients", timeout=CHECK_SECONDS).get("recipients", [])
    except (OSError, ValueError, RuntimeError) as exc:  # a refused key, or no Relay at all
        return f"can't use Relay: {exc}"
    names = {name: r for r in found for name in [r["username"], *r.get("aliases", [])]}
    who = names.get(recipient())
    if who is None:
        return f"{recipient()} is not a Relay recipient"
    if not who.get("linked_channels"):
        return f"{recipient()} has no Telegram linked yet, so nothing can reach them"
    return ""


async def check_at_start() -> None:
    """Before the first page: the header and the Today page say what it found."""
    global problem  # noqa: PLW0603 - one result, read by the header and the Today page
    if not enabled():
        return
    problem = await asyncio.to_thread(check)
    print(f"  telegram: {problem or 'checked, ' + recipient() + ' can receive'}")


# Cloudflare in front of a Relay answered Python's default "Python-urllib" agent with
# 403 "error code: 1010" - even on /healthz. Any honest agent of our own passes.
AGENT = "local-voice-coach (+relay-notify)"


def _call(method: str, path: str, body: dict | None = None, timeout: float = 15) -> dict:
    request = Request(  # noqa: S310 - http(s) only, see enabled()
        _env("RELAY_URL").rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {_env('RELAY_API_KEY')}",
            "Content-Type": "application/json",
            "User-Agent": AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) only, see enabled()
            return json.load(response)
    except HTTPError as exc:  # Relay's own error code and problems, never our content
        raw = exc.read()
        try:
            error = json.loads(raw or b"{}").get("error", {})
        except ValueError:  # not Relay answering: a proxy in front of it, e.g. Cloudflare
            error = {"code": raw[:80].decode(errors="replace").strip()}
        problems = "; ".join(error.get("problems") or [])
        raise RuntimeError(f"relay {exc.code} {error.get('code', '')} {problems}".strip()) from None


async def send(title: str, blocks: list[dict], key: str, urgency: str = "low") -> str | None:
    """Post a message. `key` makes a retry, or a second run of the same job, a no-op."""
    body = {
        "to": [recipient()],
        "source": _env("RELAY_APP"),
        "urgency": urgency,
        "title": title[:256],
        "blocks": blocks[:20],
        "idempotency_key": key[:128],
    }
    result = await asyncio.to_thread(_call, "POST", "/v1/messages", body)
    print(f"  relay: sent {result.get('id')}")
    return result.get("id")


def image(png: bytes, caption: str) -> dict:
    return {
        "type": "image",
        "base64": base64.b64encode(png).decode(),
        "content_type": "image/png",
        "caption": caption[:1024],
    }


FILE_LIMIT = 5 * 1024 * 1024  # Relay's cap on one file; past it, say where to find it


def file(data: bytes, filename: str, content_type: str, caption: str) -> dict:
    """A document to download: one per message, up to FILE_LIMIT. The filename is shown
    to the reader, so it carries nothing personal. A Relay from before file blocks
    answers 400 or 422."""
    return {
        "type": "file",
        "base64": base64.b64encode(data).decode(),
        "content_type": content_type,
        "filename": filename[:128],
        "caption": caption[:1024],
    }


def text(body: str) -> dict:
    return {"type": "text", "text": body[:4000]}


# What the jobs remember between ticks - what was sent, what was answered - kept in the
# settings table under "relay:" so a restart neither repeats nor forgets a message.
def recall(name: str) -> str:
    row = (
        store.db()
        .execute("SELECT value FROM settings WHERE key = ?", (f"relay:{name}",))
        .fetchone()
    )
    return row["value"] if row else ""


def remember(name: str, value: str) -> None:
    store.db().execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (f"relay:{name}", value),
    )
    store.db().commit()
