"""Relay: notifications to your phone through Telegram. Optional, and off unless set up.

Relay is a small notification gateway: an app posts a message, Relay formats it for
Telegram, delivers it and retries. Set these in .env (never in Settings - the key is a
secret and is read from the environment only):

    RELAY_URL      Relay's base URL, e.g. https://relay.example.com
    RELAY_API_KEY  this app's key (rk_...), created by the Relay admin
    RELAY_APP      this app's name as Relay records it, e.g. voice-coach
    RELAY_ADMIN    who to notify; optional, default "admin"

What leaves: numbers, a chart, and - if you allow it - the coach's lessons. Never audio,
never whole transcripts. Message ids are logged; contents and the key never are.
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


def enabled() -> bool:
    return bool(_env("RELAY_URL") and _env("RELAY_API_KEY") and _env("RELAY_APP"))


def _call(method: str, path: str, body: dict | None = None) -> dict:
    request = Request(
        _env("RELAY_URL").rstrip("/") + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {_env('RELAY_API_KEY')}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:  # Relay's own error code and problems, never our content
        error = json.loads(exc.read() or b"{}").get("error", {})
        problems = "; ".join(error.get("problems") or [])
        raise RuntimeError(f"relay {exc.code} {error.get('code', '')} {problems}".strip()) from None


async def send(title: str, blocks: list[dict], key: str, urgency: str = "low") -> str | None:
    """Post a message. `key` makes a retry, or a second run of the same job, a no-op."""
    body = {
        "to": [_env("RELAY_ADMIN", "admin")],
        "source": _env("RELAY_APP"),
        "urgency": urgency,
        "title": title[:256],
        "blocks": blocks[:20],
        "idempotency_key": key[:128],
    }
    result = await asyncio.to_thread(_call, "POST", "/v1/messages", body)
    print(f"  relay: sent {result.get('id')}")
    return result.get("id")


async def answer(message_id: str) -> str | None:
    """The button pressed on a question, or None if nobody has answered yet."""
    result = await asyncio.to_thread(_call, "GET", f"/v1/messages/{message_id}/answers")
    answers = result.get("answers") or []
    return answers[0].get("answer") if answers else None


def image(png: bytes, caption: str) -> dict:
    return {
        "type": "image",
        "base64": base64.b64encode(png).decode(),
        "content_type": "image/png",
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
