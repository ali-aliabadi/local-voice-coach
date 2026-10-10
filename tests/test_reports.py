"""What goes to Telegram through Relay, and when. Relay itself is faked."""

import asyncio
import datetime as dt
import json
import pathlib
import re

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from coach import picture, relay, reports, settings, store
from coach import today as today_
from coach.server import api

METRICS = {"words": 40, "wpm": 120, "fillers": 1, "pauses": 2, "longest_pause": 1, "lead_in": 1}
CHART_JS = (pathlib.Path(__file__).parents[1] / "web" / "chart.js").read_text()
TODAY = dt.date.today()


def report(session: int) -> None:
    asyncio.run(reports.after_session(session))


@pytest.mark.parametrize("key", list(picture.SERIES))
def test_the_phone_charts_use_the_apps_scales(key):
    _, domain, goal = picture.SERIES[key]
    pattern = rf"{key}: \{{\s*label: \"[^\"]*\", domain: \[([^\]]*)\], goal: \[([^\]]*)\]"
    found = re.search(pattern, CHART_JS)
    assert found, f"{key} missing from chart.js"
    parse = lambda text: tuple(float(v) for v in text.split(","))  # noqa: E731
    assert parse(found.group(1)) == domain
    assert parse(found.group(2)) == goal


def test_a_change_is_worth_mentioning_at_the_same_size_as_in_the_app():
    moved = ", ".join(f"{key}: {size:g}" for key, size in picture.MOVED.items())
    assert f"MOVED = {{ {moved} }}" in CHART_JS


def test_a_chart_draws_from_a_single_point():
    point = {"wpm": 120, "fillers": 2.1, "pauses": 6, "lead_in": 1}
    assert picture.panels([point], ["a", "b"], point)[:4] == b"\x89PNG"


def test_today_counts_the_session(counted, lessons):
    session = counted(goal=30)
    lessons(session)
    summary = lessons(session)
    now = today_.summary(TODAY)
    assert today_.streak(TODAY) == 1
    assert now["sessions"] == 1
    assert now["last"]["id"] == session
    assert now["work_on"] == summary["work_on"]
    assert now["phrases"] == summary["phrases"]


def test_the_session_report(telegram, counted, lessons):
    session = counted(goal=30)
    lessons(session)
    report(session)
    [message] = telegram.sent
    kinds = [b["type"] for b in message["blocks"]]
    assert message["title"].startswith("Session done")
    assert "of a 30 min goal" in message["title"]
    assert message["source"] == "coach"
    assert message["to"] == ["ali"]
    assert kinds[:2] == ["text", "image"]
    assert "fields" not in kinds, "the chart says the numbers"
    assert "trend" in message["blocks"][1]["caption"]
    assert message["blocks"][0]["text"].startswith("talk · 2 answers")
    assert "Since last time" not in message["blocks"][0]["text"], "nothing to compare with yet"
    assert "a breath of fresh air" in message["blocks"][-1]["text"]
    report(session)
    assert len(telegram.sent) == 1, "a session is reported once"


def test_the_report_says_in_words_what_changed_since_last_time(telegram, counted):
    counted(metrics={**METRICS, "fillers": 0})
    report(counted())
    assert (
        "Since last time: 2.5 more fillers per 100 words." in telegram.sent[-1]["blocks"][0]["text"]
    )


def test_lessons_stay_off_telegram_when_asked(telegram, counted, lessons):
    settings.set("relay_lessons", "off")
    session = counted()
    lessons(session)
    report(session)
    assert "breath of fresh air" not in json.dumps(telegram.sent)


def test_a_try_is_never_reported_and_says_so(telegram, backdate, capsys):
    session = store.start("talk", "flash-lite", "m")
    store.record(session, "you", "Short one.", METRICS)
    store.record(session, "you", "And a second, quickly.", METRICS)
    report(session)
    assert telegram.sent == [], "two answers, but under two minutes"
    assert "counts at 2 answers and 2 minutes" in capsys.readouterr().out
    backdate(session)
    report(session)
    assert len(telegram.sent) == 1, "long enough now"


def test_last_weeks_report_once_the_week_is_over(telegram, counted):
    counted()
    asyncio.run(reports.weekly(TODAY))
    assert telegram.sent == [], "last week had no practice"
    asyncio.run(reports.weekly(TODAY + dt.timedelta(days=7)))  # a week on, this is last week
    [weekly] = telegram.sent
    table = weekly["blocks"][0]
    assert weekly["title"].startswith("Last week: 1 day,")
    assert table["type"] == "table"
    assert len(table["rows"]) == 7
    assert table["rows"][TODAY.weekday()][1] != "-", "today, in its own row"
    asyncio.run(reports.weekly(TODAY + dt.timedelta(days=8)))
    assert len(telegram.sent) == 1, "once a week"


def test_nothing_is_sent_without_relays_variables(counted):
    report(counted())  # no fake: a call to Relay would fail the test
    assert not relay.enabled()
    assert relay.status() == (
        "telegram: off - not set: RELAY_URL, RELAY_API_KEY, RELAY_APP, RELAY_USER"
    )


def test_the_first_page_says_whether_telegram_is_on(monkeypatch):
    client = TestClient(Starlette(routes=api.ROUTES))
    assert client.get("/api/today").json()["wired"]["telegram"] == [
        "RELAY_URL", "RELAY_API_KEY", "RELAY_APP", "RELAY_USER",
    ]  # fmt: skip
    for name, value in {
        "RELAY_URL": "https://r.test",
        "RELAY_API_KEY": "k",
        "RELAY_APP": "a",
        "RELAY_USER": "ali",
    }.items():
        monkeypatch.setenv(name, value)
    wired = client.get("/api/today").json()["wired"]
    assert (wired["telegram"], wired["to"], wired["problem"]) == ([], "ali", "")


@pytest.mark.usefixtures("telegram")
def test_the_start_says_whether_telegram_is_on(monkeypatch):
    assert relay.status() == "telegram: on, as coach to ali"
    assert "rk_test" not in relay.status()
    monkeypatch.setenv("RELAY_URL", "relay.test")
    assert relay.status() == "telegram: off - not set: RELAY_URL starting with https://"


def test_there_is_no_default_recipient(monkeypatch):
    """Relay's skill dropped the fallback to "admin", and RELAY_ADMIN with it."""
    for name in ("RELAY_URL", "RELAY_API_KEY", "RELAY_APP"):
        monkeypatch.setenv(name, "https://r.test")
    monkeypatch.setenv("RELAY_ADMIN", "old")
    assert relay.recipient() == ""
    assert relay.missing() == ["RELAY_USER"]


@pytest.mark.parametrize(
    ("recipients", "problem"),
    [
        ([{"username": "ali", "linked_channels": ["telegram"]}], ""),
        ([{"username": "x", "aliases": ["ali"], "linked_channels": ["telegram"]}], ""),
        ([{"username": "sara", "linked_channels": ["telegram"]}], "ali is not a Relay recipient"),
        ([{"username": "ali", "linked_channels": []}], "ali has no Telegram linked yet"),
    ],
)
def test_the_check_sends_nothing_and_says_what_is_wrong(telegram, recipients, problem):
    telegram.recipients = recipients
    assert relay.check().startswith(problem)
    assert bool(relay.check()) == bool(problem)
    assert not telegram.sent


@pytest.mark.usefixtures("telegram")
def test_the_check_says_when_relay_refuses_the_key(monkeypatch):
    def refused(*_args, **_kwargs):
        raise RuntimeError("relay 401 unauthorized")

    monkeypatch.setattr(relay, "_call", refused)
    assert relay.check() == "can't use Relay: relay 401 unauthorized"


def test_the_start_checks_relay_and_the_today_page_shows_it(telegram, monkeypatch):
    monkeypatch.setattr(relay, "problem", "")
    telegram.recipients = []
    asyncio.run(relay.check_at_start())
    wired = TestClient(Starlette(routes=api.ROUTES)).get("/api/today").json()["wired"]
    assert wired["problem"] == "ali is not a Relay recipient"


def test_an_interviews_report_carries_its_verdict_in_the_title_and_no_more(telegram, counted):
    """The user asked not to be spammed: the verdict rides in the message already sent."""
    session = counted("interview", goal=45)
    full = {"rating": 7, "decision": "Yes", "summary": "SECRET CRITIQUE", "answers": 2}
    store.db().execute("UPDATE sessions SET verdict = ? WHERE id = ?", (json.dumps(full), session))
    store.db().commit()
    report(session)
    [message] = telegram.sent
    assert message["title"] == "Interview: 7/10 · Yes · 5 min of a 45 min goal"
    assert "SECRET CRITIQUE" not in json.dumps(message), "the full verdict stays on the site"
