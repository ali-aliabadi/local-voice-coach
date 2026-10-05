"""The server's edges: who may call it, which models it offers, which modes it opens."""

import warnings

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute

warnings.filterwarnings("ignore", message="Using `httpx`")  # starlette's own transition
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from coach import backends  # noqa: E402
from coach.modes import discover, state  # noqa: E402
from coach.server.guard import MIDDLEWARE  # noqa: E402

HERE, EVIL = "http://127.0.0.1:8000", "https://evil.example"


async def accept(ws):
    await ws.accept()
    await ws.close()


GUARDED = Starlette(
    middleware=MIDDLEWARE,
    routes=[
        Route("/x", lambda _r: PlainTextResponse("ok"), methods=["GET", "POST"]),
        WebSocketRoute("/ws", accept),
    ],
)


@pytest.mark.parametrize(
    ("origin", "status"),
    [
        ({"origin": HERE}, 200),
        ({}, 200),  # curl and the tests send no Origin
        ({"origin": EVIL}, 403),
    ],
)
def test_only_this_machines_own_pages_may_change_anything(origin, status):
    assert TestClient(GUARDED, base_url=HERE).post("/x", headers=origin).status_code == status


def test_no_stale_app_after_an_update():
    assert TestClient(GUARDED, base_url=HERE).get("/x").headers["cache-control"] == "no-cache"


def test_a_rebound_hostname_is_refused():
    """DNS rebinding: a page whose own domain resolves to 127.0.0.1."""
    assert TestClient(GUARDED, base_url="http://evil.example:8000").get("/x").status_code == 400


def test_a_foreign_page_cannot_open_the_practice_socket():
    with (
        pytest.raises(WebSocketDisconnect),
        TestClient(GUARDED, base_url=HERE).websocket_connect("/ws", headers={"origin": EVIL}),
    ):
        pass


def test_backends_are_offered_by_role():
    fast = {b.key for b, _ in backends.survey("fast")[0]}
    deep = {b.key for b, _ in backends.survey("deep")[0]}
    assert "flash-lite" in fast and "flash-lite" not in deep
    assert "bonsai27" in deep and "bonsai27" not in fast
    assert "flash" in fast and "flash" in deep


def test_offline_nothing_is_available_and_it_says_why(monkeypatch):
    monkeypatch.setattr(backends, "online", lambda _timeout=2.0: False)
    monkeypatch.setattr(backends, "lm_studio_models", lambda _timeout=1.5: set())
    rows, available = backends.survey("fast")
    assert not available and any(why == "no internet" for _, why in rows)


@pytest.mark.parametrize(
    ("done", "shown", "locked"),
    [
        (0, {"talk"}, set()),  # a first session sees talk alone
        (1, None, {"panel", "review"}),  # then everything, the interviews not yet open
        (2, None, set()),  # then all of it
    ],
)
def test_modes_open_as_you_practise(done, shown, locked):
    modes = discover()
    states = {name: state(module, done) for name, module in modes.items()}
    assert {n for n, s in states.items() if s != "hidden"} == (shown or set(modes))
    assert {n for n, s in states.items() if s == "locked"} == locked
