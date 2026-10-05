"""What goes to Telegram through Relay, and when. Relay itself is faked."""

import asyncio
import datetime as dt
import json
import pathlib
import re

import pytest

from coach import picture, relay, reports, settings, store
from coach import today as today_

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
    assert parse(found.group(1)) == domain and parse(found.group(2)) == goal


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
    assert today_.streak(TODAY) == 1 and now["sessions"] == 1 and now["last"]["id"] == session
    assert now["work_on"] == summary["work_on"] and now["phrases"] == summary["phrases"]


def test_the_session_report(telegram, counted, lessons):
    session = counted(goal=30)
    lessons(session)
    report(session)
    [message] = telegram.sent
    kinds = [b["type"] for b in message["blocks"]]
    assert message["title"].startswith("Session done") and "of a 30 min goal" in message["title"]
    assert message["source"] == "coach" and message["to"] == ["admin"]
    assert kinds[:2] == ["text", "image"] and "fields" not in kinds, "the chart says the numbers"
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


def test_a_try_is_never_reported(telegram, backdate):
    session = store.start("talk", "flash-lite", "m")
    store.record(session, "you", "Short one.", METRICS)
    store.record(session, "you", "And a second, quickly.", METRICS)
    report(session)
    assert telegram.sent == [], "two answers, but under two minutes"
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
    assert table["type"] == "table" and len(table["rows"]) == 7
    assert table["rows"][TODAY.weekday()][1] != "-", "today, in its own row"
    asyncio.run(reports.weekly(TODAY + dt.timedelta(days=8)))
    assert len(telegram.sent) == 1, "once a week"


def test_nothing_is_sent_without_relays_variables(counted):
    report(counted())  # no fake: a call to Relay would fail the test
    assert not relay.enabled()


@pytest.mark.parametrize(
    ("env", "recipient"),
    [
        ({"RELAY_ADMIN": "old"}, "old"),
        ({"RELAY_ADMIN": "old", "RELAY_USER": "ali"}, "ali"),
        ({}, "admin"),
    ],
)
def test_who_it_goes_to(monkeypatch, env, recipient):
    """RELAY_USER, else its old name RELAY_ADMIN, else "admin"."""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert relay.recipient() == recipient
