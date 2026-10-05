"""Reading practice back: one session, all of them, and what counts as one."""

import asyncio
import json
import sqlite3

import pytest

from coach import coach, config, history, store

METRICS = {"words": 20, "wpm": 110, "fillers": 3, "pauses": 2, "longest_pause": 1.4, "lead_in": 2.2}
WORDS = [
    {"word": "So", "start": 2.2, "end": 2.4, "filler": False, "pause": 0.0},
    {"word": "um", "start": 2.4, "end": 2.9, "filler": True, "pause": 0.0},
    {"word": "Redis", "start": 3.8, "end": 4.2, "filler": False, "pause": 0.9},
]


@pytest.fixture
def full(backdate):
    """A whole session: the partner, two answers with their words, the partner again."""
    session = store.start("talk", "flash-lite", "gemini-3.5-flash-lite")
    store.record(session, "interviewer", "Tell me about yourself.", reply_ms=900.0)
    for _ in range(2):
        store.record(session, "you", "So um Redis", METRICS, stt_ms=700, word_rows=WORDS)
    store.record(session, "interviewer", "Why Redis?", reply_ms=1100.0)
    store.finish(session)
    backdate(session)
    return session


def test_nothing_yet():
    assert history.sessions() == []
    assert history.detail(1) is None
    assert history.recent() == {}
    assert history.totals()["answers"] == 0


def test_a_session_in_full(full):
    rows = history.sessions()
    assert len(rows) == 1
    assert rows[0]["answers"] == 2
    assert rows[0]["wpm"] == 110
    detail = history.detail(full)
    assert detail is not None
    assert [t["role"] for t in detail["turns"]] == ["interviewer", "you", "you", "interviewer"]
    spoken = detail["turns"][1]
    # the per-word data survives, so an old session still shows its highlighted fillers
    assert [w["word"] for w in spoken["word_rows"] if w["filler"]] == ["um"]
    assert detail["turns"][0]["word_rows"] == []
    assert detail["averages"]["lead_in"] == 2.2
    assert detail["averages"]["fillers"] == 15.0  # 6 fillers in 40 words
    assert spoken["fillers"] == 15.0  # each answer is shown as a rate as well
    assert detail["goal_minutes"] is None
    assert round(detail["minutes"]) == 5
    assert round(detail["averages"]["spoken"], 3) == round(40 / 110, 3)
    assert [a["fillers"] for a in history.answers(full)] == [15.0, 15.0]


def test_the_clock_and_the_goal():
    session = store.start("talk", "flash-lite", "m", goal=30)
    assert store.goal(session) == 30
    assert 0 <= store.elapsed(session) < 60
    assert store.goal(store.start("talk", "flash-lite", "m")) is None


@pytest.mark.parametrize(
    ("answers", "minutes", "counts"),
    [(1, 5, False), (2, 1, False), (2, 2, True), (5, 30, True)],
)
def test_a_session_counts_at_two_answers_and_two_minutes(backdate, answers, minutes, counts):
    session = store.start("talk", "flash-lite", "m")
    for _ in range(answers):
        store.record(session, "you", "An answer.", METRICS)
    backdate(session, minutes)
    assert history.is_counted(session) is counts
    assert history.count() == int(counts)
    assert [s["id"] for s in history.sessions()] == ([session] if counts else [])


def test_a_session_with_no_answers_is_never_listed(backdate):
    empty = store.start("talk", "flash-lite", "m")
    store.record(empty, "interviewer", "hello?", reply_ms=100.0)
    backdate(empty)
    assert history.sessions() == []


@pytest.mark.usefixtures("full")
def test_totals_are_weighted_by_words_across_sessions(counted):
    counted("review", metrics={**METRICS, "words": 30, "wpm": 130, "fillers": 1, "lead_in": 1})
    assert [s["mode"] for s in history.sessions()] == ["review", "talk"]  # newest first
    newest = history.sessions()[0]["id"]
    assert [s["mode"] for s in history.sessions(before=newest)] == ["talk"]  # the next page
    totals = history.totals()
    assert totals["sessions"] == 2
    assert totals["answers"] == 4
    assert totals["words"] == 100
    # 100 words over 40/110 + 60/130 minutes, not the plain mean of 120
    assert round(totals["wpm"], 1) == 121.2
    assert totals["fillers"] == 8.0  # 8 fillers in 100 words, however they split
    assert history.recent()["answers"] == 4
    assert round(history.recent(limit=1)["fillers"], 2) == 3.33  # 1 in 30 words


@pytest.mark.parametrize(
    ("words", "fillers", "pauses"),
    [(10, 20.0, 12.0), (100, 2.0, 1.2)],
)
def test_rates_not_counts(words, fillers, pauses):
    """The same fillers in a longer answer is better, not equal."""
    rated = history.rates({"words": words, "wpm": 120, "fillers": 2, "pauses": 1})
    assert rated["fillers"] == fillers
    assert rated["pauses"] == pauses


def test_the_coachs_fixes_are_counted_by_kind(full):
    kinds = {"fixes": [{"kind": "articles"}, {"kind": "articles"}, {"kind": "tense"}]}
    detail = history.detail(full)
    assert detail is not None
    answer = detail["turns"][1]["id"]
    store.db().execute("UPDATE turns SET notes = ? WHERE id = ?", (json.dumps(kinds), answer))
    store.db().commit()
    assert history.mistakes() == [("articles", 2), ("tense", 1)]
    noted = history.detail(full)
    assert noted is not None
    assert noted["turns"][1]["notes"]["fixes"][1]["kind"] == "articles"


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ('```json\n{"fixes": []}\n```', {"fixes": []}),
        ('Sure! Here you go: {"praise": "clear"} Hope it helps.', {"praise": "clear"}),
        ("no json at all", None),
        ("", None),
    ],
)
def test_notes_parse_however_the_model_wraps_them(text, parsed):
    assert coach.parse(text) == parsed


def test_replies_followed_by_ear(full):
    assert history.listening("", "", full) == {"replies": 0, "helped": 0}  # never tracked
    store.helped(store.record(full, "interviewer", "And then?", reply_ms=1.0), ["text", "again"])
    store.helped(store.record(full, "interviewer", "Nice.", reply_ms=1.0), [])
    assert history.listening("", "", full) == {"replies": 2, "helped": 1}
    day = store.db().execute("SELECT substr(at, 1, 10) FROM turns LIMIT 1").fetchone()[0]
    assert history.listening(day, day)["helped"] == 1


def test_each_coach_task_waits_for_the_ones_before_it_never_after():
    order = []

    async def step(name, pause):
        await coach.settled(1)
        await asyncio.sleep(pause)
        order.append(name)

    async def queue():
        coach.later(1, step("notes", 0.05))
        coach.later(1, step("summary", 0))
        coach.later(1, step("sheet", 0))
        await asyncio.wait_for(coach.settled(1), timeout=2)  # a deadlock would time out

    asyncio.run(queue())
    assert order == ["notes", "summary", "sheet"]


def test_columns_added_later_reach_an_older_database(tmp_path, monkeypatch, backdate):
    old = tmp_path / "old.db"
    bare = store.SCHEMA
    for column in ("    words         INTEGER,\n", "    word_rows     TEXT"):
        bare = bare.replace(column, "")
    bare = bare.replace("audio_path    TEXT,", "audio_path    TEXT")
    with sqlite3.connect(old) as connection:
        connection.executescript(bare)
    monkeypatch.setattr(config, "DB_PATH", str(old))
    store._db = None
    session = store.start("talk", "flash-lite", "m")
    for _ in range(2):
        assert store.record(session, "you", "migrated", METRICS, word_rows=WORDS) is not None
    backdate(session)
    assert history.totals()["words"] == 40  # the added column, written and read back
