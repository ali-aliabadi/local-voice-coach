"""Signing in with a passkey, and the gate that turns away anyone who has not.

The browser does the cryptography (WebAuthn); py_webauthn checks it here. Passkeys are
discoverable, so signing in asks for nothing - the phone offers whichever passkey it
holds for this site, and that passkey says who you are. Each ceremony's challenge lives
here for five minutes under a random ticket the page sends back.

The site a passkey belongs to is the host the page was served from, so a passkey made
on the Tailscale name works only there. Behind `tailscale serve` or Caddy the request
arrives as plain http, so anything that is not localhost is taken to be https.
"""

import json
import pathlib
import secrets
import time
from urllib.parse import quote, urlsplit

import webauthn
from starlette.requests import HTTPConnection, Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .. import people, whose
from ..people import LOCAL, Person

WEB = pathlib.Path(__file__).resolve().parents[3] / "web"
COOKIE = "coach_login"
CEREMONY_SECONDS = 300  # the page fetches fresh options every 4 minutes (login.js)
OPEN = ("/login",)  # and anything under these:
OPEN_UNDER = ("/static/", "/api/passkey/")
_challenges: dict[str, tuple[bytes, float]] = {}


def site(conn: HTTPConnection) -> tuple[str, str]:
    """(the passkey's site, the page's origin) for the host this request came to."""
    host = conn.headers.get("host", "")
    name = urlsplit(f"//{host}").hostname or ""
    scheme = "http" if name in LOCAL else "https"
    return name, f"{scheme}://{host}"


def person(conn: HTTPConnection) -> Person:
    """Who is asking. The gate has already checked; off the gate, the owner."""
    return conn.scope.get("state", {}).get("person") or people.owner()


def _ticket(challenge: bytes) -> str:
    now = time.monotonic()
    for old in [t for t, (_, at) in _challenges.items() if now - at > CEREMONY_SECONDS]:
        del _challenges[old]
    ticket = secrets.token_urlsafe(16)
    _challenges[ticket] = (challenge, now)
    return ticket


def _challenge(ticket: str) -> bytes:
    challenge, at = _challenges.pop(ticket, (b"", 0.0))
    if not challenge or time.monotonic() - at > CEREMONY_SECONDS:
        raise WebAuthnException("That took too long. Try again.")
    return challenge


def refused(text: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status)


def _signed_in(request: Request, who: Person) -> Response:
    response = JSONResponse({"name": who.name})
    response.set_cookie(
        COOKIE,
        people.sign_in(who.id),
        max_age=people.LOGIN_DAYS * 86400,
        httponly=True,
        secure=site(request)[1].startswith("https"),
        samesite="lax",  # strict would sign you out when a Telegram link opens the app
    )
    return response


async def page(_request: Request) -> FileResponse:
    return FileResponse(WEB / "login.html")


async def invite(request: Request) -> JSONResponse:
    """Who a link is for, so the page can greet them. 404 for a used or stale one."""
    who = people.invited(request.query_params.get("token", ""))
    if who is None:
        return refused("This link has been used or has expired. Ask for a new one.", 404)
    return JSONResponse({"name": who.name, "passkeys": len(people.passkey_ids(who.id))})


async def register_options(request: Request) -> JSONResponse:
    body = await request.json()
    who = people.invited(body.get("token", ""))
    if who is None:
        return refused("This link has been used or has expired. Ask for a new one.", 404)
    options = webauthn.generate_registration_options(
        rp_id=site(request)[0],
        rp_name="Speaking practice",
        user_id=f"person-{who.id}".encode(),
        user_name=who.name,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(i))
            for i in people.passkey_ids(who.id)
        ],
    )
    ticket = _ticket(options.challenge)
    return JSONResponse({"ticket": ticket, "options": json.loads(options_to_json(options))})


async def register(request: Request) -> Response:
    body = await request.json()
    rp_id, origin = site(request)
    try:
        verified = webauthn.verify_registration_response(
            credential=body.get("credential") or {},
            expected_challenge=_challenge(body.get("ticket", "")),
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        return refused(f"The passkey was not accepted: {exc}")
    who = people.use_invite(body.get("token", ""))  # used up only once it has worked
    if who is None:
        return refused("This link has been used or has expired. Ask for a new one.", 404)
    credential_id = bytes_to_base64url(verified.credential_id)
    people.keep_passkey(who.id, credential_id, verified.credential_public_key, verified.sign_count)
    print(f"  {who.name} added a passkey")
    return _signed_in(request, who)


def asking(request: Request, allow: list[str] | None = None) -> JSONResponse:
    """A sign-in ceremony's options: any passkey of this site's, or only those in `allow`."""
    options = webauthn.generate_authentication_options(
        rp_id=site(request)[0],
        user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(i)) for i in allow]
        if allow
        else None,
    )
    ticket = _ticket(options.challenge)
    return JSONResponse({"ticket": ticket, "options": json.loads(options_to_json(options))})


def proved(request: Request, body: dict) -> int | str:
    """Whose passkey answered the ceremony: their person id, or why it was refused."""
    credential = body.get("credential") or {}
    stored = people.passkey(str(credential.get("id", "")))
    if stored is None:
        return "This passkey is not one this server knows. It may have been removed."
    rp_id, origin = site(request)
    try:
        verified = webauthn.verify_authentication_response(
            credential=credential,
            expected_challenge=_challenge(body.get("ticket", "")),
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=stored["public_key"],
            credential_current_sign_count=stored["sign_count"],
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        return f"The passkey was not accepted: {exc}"
    people.passkey_used(stored["id"], verified.new_sign_count)
    return int(stored["person_id"])


async def login_options(request: Request) -> JSONResponse:
    return asking(request)


async def login(request: Request) -> Response:
    found = proved(request, await request.json())
    if isinstance(found, str):
        return refused(found)
    who = people.get(found)
    return _signed_in(request, who) if who else refused("That person was removed.")


async def logout(request: Request) -> Response:
    people.sign_out(request.cookies.get(COOKIE, ""))
    response = JSONResponse({})
    response.delete_cookie(COOKIE)
    return response


ROUTES = [
    Route("/login", page),
    Route("/api/passkey/invite", invite),
    Route("/api/passkey/register/options", register_options, methods=["POST"]),
    Route("/api/passkey/register", register, methods=["POST"]),
    Route("/api/passkey/login/options", login_options, methods=["POST"]),
    Route("/api/passkey/login", login, methods=["POST"]),
    Route("/api/passkey/logout", logout, methods=["POST"]),
]


def _open(path: str) -> bool:
    return path in OPEN or path.startswith(OPEN_UNDER)


class Gate:
    """Every request but the sign-in page's own carries a signed-in browser's cookie, or
    is turned away: a page to /login, the API with 401, the practice socket closed."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or _open(scope["path"]):
            return await self.app(scope, receive, send)
        conn = HTTPConnection(scope)
        who = people.signed_in(conn.cookies.get(COOKIE, "")) if people.required() else None
        if who is None and not people.required():
            who = people.owner()
        if who is not None:
            scope.setdefault("state", {})["person"] = who
            # Everything below reads and writes this person's rows; the owner's are NULL.
            acting = whose.acting.set(None if who.id == people.owner().id else who.id)
            try:
                return await self.app(scope, receive, send)
            finally:
                whose.acting.reset(acting)
        if scope["type"] == "websocket":
            await receive()  # the connect event, then refuse it
            await send({"type": "websocket.close", "code": 1008})
            return None
        response: Response
        if scope["path"].startswith("/api/"):
            response = refused("Sign in first.", 401)
        else:
            response = RedirectResponse(f"/login?next={quote(scope['path'])}", status_code=303)
        return await response(scope, receive, send)
