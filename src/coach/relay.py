"""Relay: notifications to your phone through Telegram. Optional, and off unless set up.

Relay is a small notification gateway: an app posts a message, Relay formats it for
Telegram, delivers it and retries. Set these in .env (never in Settings - the key is a
secret and is read from the environment only):

    RELAY_URL      Relay's base URL, e.g. https://relay.example.com
    RELAY_API_KEY  this app's key (rk_...), created by the Relay admin
    RELAY_APP      this app's name as Relay records it, e.g. voice-coach
    RELAY_USER     who this app sends to; optional, default "admin" (RELAY_ADMIN, its
                   old name, still works when RELAY_USER is unset)

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
    """Who this app sends to, as Relay's skill resolves it."""
    return _env("RELAY_USER") or _env("RELAY_ADMIN") or "admin"


def enabled() -> bool:
    url = _env("RELAY_URL")
    return url.startswith(("http://", "https://")) and bool(
        _env("RELAY_API_KEY") and _env("RELAY_APP")
    )


# Cloudflare in front of a Relay answered Python's default "Python-urllib" agent with
# 403 "error code: 1010" - even on /healthz. Any honest agent of our own passes.
AGENT = "local-voice-coach (+relay-notify)"


def _call(method: str, path: str, body: dict | None = None) -> dict:
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
        with urlopen(request, timeout=15) as response:  # noqa: S310 - http(s) only, see enabled()
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
