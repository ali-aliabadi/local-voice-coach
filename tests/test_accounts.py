"""Each person's own: history, profile, settings, Telegram. One never sees another's."""

import asyncio
import contextlib
import sqlite3
import warnings

import pytest

warnings.filterwarnings("ignore", message="Using `httpx`")
from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from coach import history, people, profile, relay, settings, store, today, whose  # noqa: E402
from coach.server import api, login, past  # noqa: E402

HOST = "coach.tail.ts.net"


@contextlib.contextmanager
def acting_as(person_id):
    token = whose.acting.set(person_id)
    try:
        yield
    finally:
        whose.acting.reset(token)


@pytest.fixture
def sara():
    people.owner()
    return people.add("Sara", "sara")


def test_each_person_sees_only_their_own_sessions(counted, sara):
    mine = counted()
    with acting_as(sara.id):
        hers = counted()
        assert [s["id"] for s in history.sessions()] == [hers]
        assert history.count() == 1
        assert history.detail(mine) is None
        assert store.resume(mine) is None
        assert store.owns(hers)
        assert history.totals()["sessions"] == 1
    assert [s["id"] for s in history.sessions()] == [mine]
    assert history.detail(hers) is None


def test_sessions_from_before_accounts_are_the_owners(counted, sara):
    """Real history has no person on it: it must stay the owner's, untouched."""
    old = counted()
    assert (
        store.db().execute("SELECT person_id FROM sessions WHERE id = ?", (old,)).fetchone()[0]
        is None
    )
    assert store.owns(old)
    with acting_as(sara.id):
        assert not store.owns(old)


def test_today_and_recaps_are_your_own(counted, lessons, sara):
    lessons(counted())
    with acting_as(sara.id):
        assert today.summary(__import__("datetime").date.today())["work_on"] == []
        assert profile.recaps() == ""


def test_a_profile_is_never_borrowed(sara):
    profile.save({"name": "Ali"})
    with acting_as(sara.id):
        assert profile.get("name") == ""
        profile.save({"name": "Sara"})
        assert profile.get("name") == "Sara"
    assert profile.get("name") == "Ali"


def test_settings_start_from_the_owners_and_then_are_your_own(sara):
    settings.set("tts_speed", 0.8)
    with acting_as(sara.id):
        assert settings.get("tts_speed") == 0.8
        settings.set("tts_speed", 1.0)
        assert settings.get("tts_speed") == 1.0  # back to the default, not to the owner's
    assert settings.get("tts_speed") == 0.8


def test_shared_settings_are_one_for_everybody(sara):
    with acting_as(sara.id):
        settings.set("lm_studio_url", "http://box:1234/v1")
    assert settings.get("lm_studio_url") == "http://box:1234/v1"
    assert "lm_studio_url" in settings.SHARED
    assert "tts_voice" not in settings.SHARED


def test_forgetting_deletes_only_your_own(counted, sara):
    mine = counted()
    with acting_as(sara.id):
        counted()
        store.forget_everything()
        assert history.count() == 0
    assert [s["id"] for s in history.sessions()] == [mine]


@pytest.mark.usefixtures("telegram")
def test_telegram_goes_to_each_persons_own_relay_name(sara):
    assert relay.recipient() == "ali"
    with acting_as(sara.id):
        assert relay.recipient() == "sara"
        relay.remember("weekly", "x")
        assert relay.recall("weekly") == "x"
    assert relay.recall("weekly") == ""
    nobody = people.add("Sam")
    with acting_as(nobody.id):
        assert not relay.enabled()
        assert "your Relay username" in relay.missing()


def test_the_coachs_work_after_a_session_stays_with_its_person(sara):
    """Background tasks copy the context they were made in."""

    async def later():
        return whose.acting.get()

    async def made_by_sara():
        with acting_as(sara.id):
            task = asyncio.create_task(later())
        return await task

    assert asyncio.run(made_by_sara()) == sara.id


@pytest.fixture
def served(monkeypatch):
    connect = sqlite3.connect
    monkeypatch.setattr(
        store.sqlite3, "connect", lambda path: connect(path, check_same_thread=False)
    )
    monkeypatch.setenv("ALLOWED_HOSTS", HOST)

    async def acting(_request):
        return JSONResponse({"acting": whose.acting.get()})

    app = Starlette(
        middleware=[Middleware(login.Gate)],
        routes=[Route("/acting", acting), *api.ROUTES, *past.ROUTES],
    )
    return TestClient(app, base_url=f"https://{HOST}")


def test_the_gate_acts_as_whoever_signed_in(served, sara):
    served.cookies.set(login.COOKIE, people.sign_in(sara.id))
    assert served.get("/acting").json() == {"acting": sara.id}
    served.cookies.set(login.COOKIE, people.sign_in(people.owner().id))
    assert served.get("/acting").json() == {"acting": None}


def test_only_an_admin_changes_the_servers_settings(served, sara):
    served.cookies.set(login.COOKIE, people.sign_in(sara.id))
    served.post("/api/settings", json={"lm_studio_url": "http://evil/v1", "tts_speed": "0.9"})
    assert settings.get("lm_studio_url") != "http://evil/v1"
    with acting_as(sara.id):
        assert settings.get("tts_speed") == 0.9


def test_someone_elses_session_is_not_found(served, counted, sara):
    mine = counted()
    served.cookies.set(login.COOKIE, people.sign_in(sara.id))
    assert served.get(f"/api/sessions/{mine}").status_code == 404
    assert served.get(f"/api/sessions/{mine}/sheet.pdf").status_code == 404
    assert served.post(f"/api/sessions/{mine}/coach").status_code == 404
    turn = store.db().execute("SELECT id FROM turns WHERE session_id = ?", (mine,)).fetchone()[0]
    assert served.get(f"/api/audio/{turn}").status_code == 404
