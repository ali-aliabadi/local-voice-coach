"""Accounts and passkey sign-in: who may use a server that more than this machine reaches."""

import asyncio
import sqlite3
import warnings
from types import SimpleNamespace

import pytest

warnings.filterwarnings("ignore", message="Using `httpx`")
from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route, WebSocketRoute  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from coach import people, relay, store, whose  # noqa: E402
from coach.server import accounts, login  # noqa: E402

HOST = "coach.tail.ts.net"


async def whoami(request):
    return JSONResponse({"name": login.person(request).name})


async def accept(ws):
    await ws.accept()
    await ws.close()


APP = Starlette(
    middleware=[Middleware(login.Gate)],
    routes=[
        *login.ROUTES,
        *accounts.ROUTES,
        Route("/api/me", whoami),
        Route("/history", whoami),
        WebSocketRoute("/ws", accept),
    ],
)


@pytest.fixture(autouse=True)
def one_database_for_both_threads(monkeypatch):
    """The test reads what the app, on TestClient's thread, wrote."""
    connect = sqlite3.connect
    monkeypatch.setattr(
        store.sqlite3, "connect", lambda path: connect(path, check_same_thread=False)
    )


@pytest.fixture
def served(monkeypatch):
    """Reachable beyond localhost, as on the VPS."""
    monkeypatch.setenv("ALLOWED_HOSTS", HOST)
    return TestClient(APP, base_url=f"https://{HOST}")


def signed_in_as(client, who):
    client.cookies.set(login.COOKIE, people.sign_in(who.id))
    return client


def test_on_localhost_nobody_signs_in_and_it_is_the_owner():
    client = TestClient(APP, base_url="http://127.0.0.1:8000")
    assert client.get("/api/me").json() == {"name": "me"}
    assert people.owner().admin


@pytest.mark.usefixtures("telegram")
def test_the_owner_is_named_after_their_relay_recipient():
    assert people.owner().name == "ali"
    assert people.owner().relay == "ali"


def test_served_beyond_localhost_every_door_is_shut_without_a_sign_in(served):
    assert served.get("/api/me").status_code == 401
    page = served.get("/history", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"] == "/login?next=/history"
    with pytest.raises(WebSocketDisconnect), served.websocket_connect("/ws") as ws:
        ws.receive_text()
    assert served.post("/api/passkey/login/options").status_code == 200  # the way in is open


def test_a_signed_in_browser_is_that_person(served):
    sara = people.add("Sara")
    assert signed_in_as(served, sara).get("/api/me").json() == {"name": "Sara"}


def test_a_forged_or_signed_out_cookie_is_refused(served):
    served.cookies.set(login.COOKIE, "made-up")
    assert served.get("/api/me").status_code == 401
    token = people.sign_in(people.owner().id)
    people.sign_out(token)
    served.cookies.set(login.COOKIE, token)
    assert served.get("/api/me").status_code == 401


def test_only_hashes_are_stored():
    token = people.sign_in(people.owner().id)
    link = people.invite(people.owner().id, 10)
    rows = people._db().execute(
        "SELECT token_hash FROM logins UNION SELECT token_hash FROM invites"
    )
    stored = {r[0] for r in rows}
    assert token not in stored
    assert link not in stored


def test_an_invite_works_once_and_not_after_it_expires():
    who = people.add("Sara")
    token = people.invite(who.id, 10)
    assert people.invited(token) == who
    assert people.use_invite(token) == who
    assert people.invited(token) is None
    assert people.invited(people.invite(who.id, -1)) is None


def test_a_used_link_cannot_make_a_passkey(served):
    reply = served.post("/api/passkey/register/options", json={"token": "nope"})
    assert reply.status_code == 404


def test_signing_in_with_a_passkey_sets_a_cookie_for_that_person(served, monkeypatch):
    sara = people.add("Sara")
    people.keep_passkey(sara.id, "cred-1", b"public", 3)
    ticket = served.post("/api/passkey/login/options").json()["ticket"]
    checked = {}

    def verify(**kwargs):
        checked.update(kwargs)
        return SimpleNamespace(new_sign_count=4)

    monkeypatch.setattr(login.webauthn, "verify_authentication_response", verify)
    reply = served.post(
        "/api/passkey/login", json={"ticket": ticket, "credential": {"id": "cred-1"}}
    )
    assert reply.json() == {"name": "Sara"}
    assert checked["expected_rp_id"] == HOST
    assert checked["expected_origin"] == f"https://{HOST}"
    assert checked["require_user_verification"]
    stored = people.passkey("cred-1")
    assert stored is not None
    assert stored["sign_count"] == 4
    assert "httponly" in reply.headers["set-cookie"].lower()
    assert served.get("/api/me").json() == {"name": "Sara"}


def test_a_ticket_is_good_for_one_ceremony(served, monkeypatch):
    people.keep_passkey(people.owner().id, "cred-1", b"public", 0)
    monkeypatch.setattr(
        login.webauthn,
        "verify_authentication_response",
        lambda **_: SimpleNamespace(new_sign_count=1),
    )
    ticket = served.post("/api/passkey/login/options").json()["ticket"]
    body = {"ticket": ticket, "credential": {"id": "cred-1"}}
    assert served.post("/api/passkey/login", json=body).status_code == 200
    assert served.post("/api/passkey/login", json=body).status_code == 400


def test_registering_uses_up_the_invite_and_signs_in(served, monkeypatch):
    sara = people.add("Sara")
    token = people.invite(sara.id, 10)
    options = served.post("/api/passkey/register/options", json={"token": token}).json()
    assert options["options"]["authenticatorSelection"]["residentKey"] == "required"
    made = SimpleNamespace(credential_id=b"\x01\x02", credential_public_key=b"pk", sign_count=0)
    monkeypatch.setattr(login.webauthn, "verify_registration_response", lambda **_: made)
    body = {"ticket": options["ticket"], "token": token, "credential": {}}
    assert served.post("/api/passkey/register", json=body).json() == {"name": "Sara"}
    assert people.passkey_ids(sara.id) == ["AQI"]
    assert people.invited(token) is None


def test_only_an_admin_invites_or_locks_out(served):
    sara = people.add("Sara")
    signed_in_as(served, sara)
    assert served.post("/api/people", json={"name": "Sam"}).status_code == 403
    assert served.post(f"/api/people/{people.owner().id}/revoke").status_code == 403
    assert served.post(f"/api/people/{people.owner().id}/link").status_code == 403
    assert served.post(f"/api/people/{sara.id}/link").status_code == 200  # her own device
    assert [p["name"] for p in served.get("/api/people").json()["people"]] == ["Sara"]


def test_an_invite_goes_to_their_telegram(served, telegram):
    signed_in_as(served, people.owner())
    made = served.post("/api/people", json={"name": "Sara", "relay": "sara"}).json()
    assert made["sent"] == "telegram"
    assert made["link"].startswith(f"https://{HOST}/login?invite=")
    sent = telegram.sent[-1]
    assert sent["to"] == ["sara"]
    assert made["link"] in sent["blocks"][0]["text"]


def test_locking_out_ends_every_sign_in_but_not_your_own(served):
    owner, sara = people.owner(), people.add("Sara")
    phone = TestClient(APP, base_url=f"https://{HOST}")
    signed_in_as(phone, sara)
    people.keep_passkey(sara.id, "cred-1", b"pk", 0)
    signed_in_as(served, owner)
    assert served.post(f"/api/people/{owner.id}/revoke").status_code == 400
    assert served.post(f"/api/people/{sara.id}/revoke").status_code == 200
    assert phone.get("/api/me").status_code == 401
    assert people.passkey_ids(sara.id) == []


@pytest.mark.usefixtures("served")
def test_the_first_way_in_is_a_link_at_the_start(capsys):
    asyncio.run(accounts.bootstrap())
    assert f"https://{HOST}/login?invite=" in capsys.readouterr().out
    people.keep_passkey(people.owner().id, "cred-1", b"pk", 0)
    asyncio.run(accounts.bootstrap())
    assert "invite" not in capsys.readouterr().out


def test_relay_sends_to_whoever_is_named(telegram):
    asyncio.run(relay.send("t", [], key="k", to="sara"))
    assert telegram.sent[-1]["to"] == ["sara"]


def test_relay_user_set_after_the_first_start_is_taken_up(monkeypatch):
    """The first start on a server often comes before .env has Relay in it."""
    first = people.owner()
    assert first.name == "me"
    monkeypatch.setenv("RELAY_USER", "ali")
    assert people.owner() == people.Person(first.id, "ali", "ali", True)
    assert people.get(first.id) == people.Person(first.id, "ali", "ali", True)


def test_the_owner_is_the_owner_whoever_is_asking(monkeypatch):
    monkeypatch.setenv("RELAY_USER", "ali")
    sara = people.add("Sara", "sara")
    acting = whose.acting.set(sara.id)
    try:
        assert people.owner().relay == "ali"
    finally:
        whose.acting.reset(acting)
