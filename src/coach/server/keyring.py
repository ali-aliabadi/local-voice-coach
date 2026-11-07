"""The Settings page's keys and Telegram: an admin's, and only after a fresh passkey.

Reading shows where each value comes from and, for a secret, only its last four
characters. Changing anything takes a passkey from the last ten minutes, on top of being
signed in: a phone left unlocked and signed in for 30 days should not be enough to swap
the server's keys. On localhost nobody has a passkey and nobody else can reach the page,
so it asks for none there. What .env sets is shown and cannot be changed here.
"""

import hashlib
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import people, relay, vault
from .login import COOKIE, asking, person, proved, refused

FRESH_SECONDS = 600
_fresh: dict[str, float] = {}  # a signed-in browser's cookie hash -> when it last proved it

LABELS = {
    "RELAY_URL": ("Relay URL", "Where your Relay runs, starting https://"),
    "RELAY_APP": ("App name", "This app's name as your Relay knows it, e.g. voice-coach."),
    "RELAY_USER": ("Your Relay username", "Where your own links and reports go."),
    "RELAY_API_KEY": ("Relay API key", "This app's key (rk_...), made by whoever runs Relay."),
}


def _browser(request: Request) -> str:
    return hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest()


def fresh(request: Request) -> bool:
    if not people.required():
        return True
    return time.monotonic() - _fresh.get(_browser(request), -FRESH_SECONDS) < FRESH_SECONDS


def _guard(request: Request, changing: bool = True) -> JSONResponse | None:
    if not person(request).admin:
        return refused("Only an admin can see or change the server's keys.", 403)
    if changing and not fresh(request):
        return refused("Confirm with your passkey first.", 401)
    return None


def _relay_rows() -> list[dict]:
    rows = []
    for name in vault.RELAY:
        found = vault.value(name)
        secret = name in vault.SECRET
        label, help_text = LABELS[name]
        rows.append(
            {
                "name": name,
                "label": label,
                "help": help_text,
                "secret": secret,
                "value": vault.masked(found) if secret and found else found,
                "from": vault.source(name),
            }
        )
    return rows


async def show(request: Request) -> JSONResponse:
    if blocked := _guard(request, changing=False):
        return blocked
    return JSONResponse(
        {
            "keys": vault.listed(),
            "relay": _relay_rows(),
            "telegram": {"missing": relay.missing(), "problem": relay.problem},
            "fresh": fresh(request),
            "required": people.required(),
        }
    )


async def confirm_options(request: Request) -> JSONResponse:
    if blocked := _guard(request, changing=False):
        return blocked
    return asking(request, people.passkey_ids(person(request).id))


async def confirm(request: Request) -> JSONResponse:
    if blocked := _guard(request, changing=False):
        return blocked
    found = proved(request, await request.json())
    if isinstance(found, str):
        return refused(found)
    if found != person(request).id:
        return refused("That passkey is someone else's.", 403)
    _fresh[_browser(request)] = time.monotonic()
    return JSONResponse({"fresh": True})


async def add_key(request: Request) -> JSONResponse:
    if blocked := _guard(request):
        return blocked
    try:
        vault.add_key(str((await request.json()).get("key", "")))
    except ValueError as exc:
        return refused(str(exc))
    return await show(request)


async def remove_key(request: Request) -> JSONResponse:
    if blocked := _guard(request):
        return blocked
    if not vault.remove_key(request.path_params["id"]):
        return refused("That key is set in .env, or was already removed.", 404)
    return await show(request)


async def save_relay(request: Request) -> JSONResponse:
    """Blank leaves a secret as it is; anything .env sets is left to .env."""
    if blocked := _guard(request):
        return blocked
    body = await request.json()
    for name in vault.RELAY:
        if name not in body or vault.source(name) == "env":
            continue
        text = str(body[name]).strip()
        if name in vault.SECRET and not text:
            continue
        vault.put(name, text)
    if "RELAY_USER" in body and vault.source("RELAY_USER") != "env":
        people.set_relay(people.owner().id, vault.value("RELAY_USER"))
    await relay.recheck(force=True)  # say now whether it works, not at the next start
    return await show(request)


ROUTES = [
    Route("/api/keyring", show),
    Route("/api/keyring/confirm/options", confirm_options, methods=["POST"]),
    Route("/api/keyring/confirm", confirm, methods=["POST"]),
    Route("/api/keyring/keys", add_key, methods=["POST"]),
    Route("/api/keyring/keys/{id}/remove", remove_key, methods=["POST"]),
    Route("/api/keyring/relay", save_relay, methods=["POST"]),
]
