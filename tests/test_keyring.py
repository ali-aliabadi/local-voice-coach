"""The server's keys and Telegram, set from the Settings page: an admin's, after a passkey."""

import warnings
from types import SimpleNamespace

import pytest

warnings.filterwarnings("ignore", message="Using `httpx`")
from starlette.applications import Starlette  # noqa: E402
from starlette.middleware import Middleware  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from coach import people, relay, vault  # noqa: E402
from coach.server import keyring, login  # noqa: E402
from tests.conftest import FakeRelay  # noqa: E402
from tests.test_people import HOST, one_database_for_both_threads, signed_in_as  # noqa: E402, F401

APP = Starlette(middleware=[Middleware(login.Gate)], routes=[*login.ROUTES, *keyring.ROUTES])
KEY = "AIzaSy" + "k" * 33


@pytest.fixture(autouse=True)
def nobody_fresh():
    keyring._fresh.clear()


@pytest.fixture
def admin(served):
    people.keep_passkey(people.owner().id, "cred-owner", b"pk", 0)
    return signed_in_as(served, people.owner())


def confirmed(client, monkeypatch, credential="cred-owner"):
    monkeypatch.setattr(
        login.webauthn,
        "verify_authentication_response",
        lambda **_: SimpleNamespace(new_sign_count=1),
    )
    ticket = client.post("/api/keyring/confirm/options").json()["ticket"]
    return client.post(
        "/api/keyring/confirm", json={"ticket": ticket, "credential": {"id": credential}}
    )


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", HOST)
    return TestClient(APP, base_url=f"https://{HOST}")


def test_only_an_admin_sees_the_keys(served):
    sara = people.add("Sara")
    assert signed_in_as(served, sara).get("/api/keyring").status_code == 403


def test_nothing_changes_without_a_fresh_passkey(admin, monkeypatch):
    assert admin.post("/api/keyring/keys", json={"key": KEY}).status_code == 401
    assert vault.gemini_keys() == []
    assert confirmed(admin, monkeypatch).status_code == 200
    shown = admin.post("/api/keyring/keys", json={"key": KEY})
    assert shown.status_code == 200
    assert vault.gemini_keys() == [KEY]
    assert KEY not in shown.text  # write-only: the browser gets the last four, never the key
    assert shown.json()["keys"][0]["shown"] == "…kkkk"


def test_a_passkey_confirms_only_its_own_person(admin, monkeypatch):
    sara = people.add("Sara")
    people.keep_passkey(sara.id, "cred-sara", b"pk", 0)
    assert confirmed(admin, monkeypatch, "cred-sara").status_code == 403
    assert not admin.get("/api/keyring").json()["fresh"]


def test_a_key_is_removed_by_its_id_and_one_in_env_stays(admin, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "from-env-key")
    vault.add_key(KEY)
    confirmed(admin, monkeypatch)
    rows = {k["from"]: k["id"] for k in admin.get("/api/keyring").json()["keys"]}
    assert admin.post(f"/api/keyring/keys/{rows['env']}/remove").status_code == 404
    assert admin.post(f"/api/keyring/keys/{rows['app']}/remove").status_code == 200
    assert vault.gemini_keys() == ["from-env-key"]


def test_telegram_set_in_the_app_switches_relay_on(admin, monkeypatch):
    fake = FakeRelay()
    monkeypatch.setattr(relay, "_call", fake)
    confirmed(admin, monkeypatch)
    body = {
        "RELAY_URL": "https://relay.test",
        "RELAY_APP": "coach",
        "RELAY_USER": "ali",
        "RELAY_API_KEY": "rk_secret_value_1234",
    }
    shown = admin.post("/api/keyring/relay", json=body).json()
    assert shown["telegram"] == {"missing": [], "problem": ""}
    assert fake.via == ("https://relay.test", "rk_secret_value_1234")
    assert "rk_secret_value_1234" not in str(shown)
    assert people.owner().relay == "ali"  # their own links go there too
    admin.post("/api/keyring/relay", json={**body, "RELAY_API_KEY": ""})
    assert vault.value("RELAY_API_KEY") == "rk_secret_value_1234"  # blank keeps it


def test_the_environment_wins_and_cannot_be_changed_here(admin, monkeypatch):
    monkeypatch.setenv("RELAY_URL", "https://from-env.test")
    confirmed(admin, monkeypatch)
    admin.post("/api/keyring/relay", json={"RELAY_URL": "https://other.test"})
    assert vault.value("RELAY_URL") == "https://from-env.test"
    rows = {r["name"]: r for r in admin.get("/api/keyring").json()["relay"]}
    assert rows["RELAY_URL"]["from"] == "env"


def test_on_localhost_no_passkey_is_asked_for():
    client = TestClient(APP, base_url="http://127.0.0.1:8000")
    assert client.post("/api/keyring/keys", json={"key": KEY}).status_code == 200
    assert vault.gemini_keys() == [KEY]


def test_something_that_is_not_a_key_is_refused():
    with pytest.raises(ValueError, match="Gemini key"):
        vault.add_key("hello world")
