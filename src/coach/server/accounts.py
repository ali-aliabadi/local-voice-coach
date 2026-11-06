"""The people page's routes: who is here, inviting someone, adding a device, removing one.

Only an admin adds or removes people; anyone may make a link for another device of their
own. A link goes to the person's Telegram through Relay when they have a Relay recipient,
and is always shown to whoever made it, to send another way or open on this device.
"""

import hashlib

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import people, relay
from ..people import Person
from .login import person, site

INVITED = "{name}, here is your link to the speaking practice app. Open it on your phone and "
DEVICE = "Here is the link to sign in on another device. Open it there and "
ENDING = "make a passkey: no password, just your face, fingerprint or screen lock.\n\n{url}"


async def deliver(who: Person, url: str, opening: str) -> str:
    """Send a link to their Telegram; "telegram" if it went, "" if it is yours to pass on."""
    if not (relay.enabled() and who.relay):
        return ""
    words = (opening + ENDING).format(name=who.name, url=url)
    key = "link:" + hashlib.sha256(url.encode()).hexdigest()[:24]
    try:
        await relay.send("Your sign-in link", [relay.text(words)], key=key, to=who.relay)
    except (OSError, RuntimeError) as exc:
        print(f"  relay: the link for {who.name} did not go: {exc}")
        return ""
    return "telegram"


def link(origin: str, token: str) -> str:
    return f"{origin}/login?invite={token}"


async def bootstrap() -> None:
    """With sign-in required and no passkey yet, the owner needs a first way in: a link,
    printed here and sent to their Telegram. A new one each start until it is used."""
    if not people.required():
        return
    owner = people.owner()
    if people.passkey_ids(owner.id):
        return
    url = link(f"https://{people.hosts()[0]}", people.invite(owner.id, people.INVITE_HOURS * 60))
    sent = await deliver(owner, url, INVITED)
    print(f"  no passkey yet. Open this on your phone{' (also sent to Telegram)' if sent else ''}:")
    print(f"  {url}")


def _row(row: dict) -> dict:
    return {k: row[k] for k in ("id", "name", "relay", "admin", "passkeys", "last_seen")}


async def get_people(request: Request) -> JSONResponse:
    me = person(request)
    rows = [_row(r) | {"pending": people.pending(r["id"])} for r in people.everyone()]
    return JSONResponse(
        {
            "me": me._asdict(),
            "required": people.required(),
            "telegram": relay.enabled(),
            "people": rows if me.admin else [r for r in rows if r["id"] == me.id],
        }
    )


def _admin_only(request: Request) -> JSONResponse | None:
    if person(request).admin:
        return None
    return JSONResponse({"error": "Only an admin can do that."}, status_code=403)


async def add_person(request: Request) -> JSONResponse:
    if refused := _admin_only(request):
        return refused
    body = await request.json()
    try:
        who = people.add(str(body.get("name", "")), str(body.get("relay", "")))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    url = link(site(request)[1], people.invite(who.id, people.INVITE_HOURS * 60))
    return JSONResponse({"link": url, "sent": await deliver(who, url, INVITED), "id": who.id})


async def new_link(request: Request) -> JSONResponse:
    """A link for another device: your own, or - for an admin - anyone's."""
    me, target = person(request), int(request.path_params["id"])
    if target != me.id and (refused := _admin_only(request)):
        return refused
    who = people.get(target)
    if who is None:
        return JSONResponse({"error": "No such person."}, status_code=404)
    minutes = people.DEVICE_MINUTES if who.id == me.id else people.INVITE_HOURS * 60
    url = link(site(request)[1], people.invite(who.id, minutes))
    opening = DEVICE if who.id == me.id else INVITED
    return JSONResponse({"link": url, "sent": await deliver(who, url, opening)})


async def revoke(request: Request) -> JSONResponse:
    """Signs them out everywhere and removes their passkeys. Their history stays."""
    if refused := _admin_only(request):
        return refused
    target = int(request.path_params["id"])
    if target == person(request).id:
        return JSONResponse({"error": "You cannot lock yourself out."}, status_code=400)
    people.revoke(target)
    return JSONResponse({})


ROUTES = [
    Route("/api/people", get_people, methods=["GET"]),
    Route("/api/people", add_person, methods=["POST"]),
    Route("/api/people/{id:int}/link", new_link, methods=["POST"]),
    Route("/api/people/{id:int}/revoke", revoke, methods=["POST"]),
]
