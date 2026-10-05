"""Telegram reports through Relay. Run: python tests/test_reports.py"""

import asyncio
import datetime as dt
import json
import os
import pathlib
import re
import tempfile

from coach import config  # noqa: I001

config.DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "reports.db")
# config read the developer's .env on import; nothing of theirs may reach this test
os.environ.update(RELAY_URL="https://relay.test", RELAY_API_KEY="rk_test", RELAY_APP="coach")
for name in ("RELAY_USER", "RELAY_ADMIN"):
    os.environ.pop(name, None)

from coach import history, picture, relay, reports, settings, store  # noqa: E402
from coach import today as today_  # noqa: E402

# ---- Relay itself is faked by reassigning the one function that talks to it ----
sent: list[dict] = []
takes_files = True  # an older Relay refuses the file block


def fake_call(method, _path, body=None):
    files = [b for b in (body or {}).get("blocks", []) if b["type"] == "file"]
    if method == "POST" and not takes_files and files:
        raise RuntimeError("relay 422 invalid_request blocks[0].type: unknown")
    assert method == "POST", "nothing is ever read back from Relay"
    sent.append(body)
    return {"id": f"msg_{len(sent)}", "status": "queued"}


relay._call = fake_call
run = asyncio.run
today = dt.date.today()

# ---- the charts on a phone use the same scales as the charts in the app ----
chart_js = (pathlib.Path(__file__).parents[1] / "web" / "chart.js").read_text()
for key, (_, domain, goal) in picture.SERIES.items():
    found = re.search(rf"{key}: \{{\s*label: \"[^\"]*\", domain: \[([^\]]*)\], goal: \[([^\]]*)\]",
                      chart_js)  # fmt: skip
    assert found, f"{key} missing from chart.js"
    parse = lambda text: tuple(float(v) for v in text.split(","))  # noqa: E731
    assert parse(found.group(1)) == domain and parse(found.group(2)) == goal, key
moved = ", ".join(f"{key}: {size:g}" for key, size in picture.MOVED.items())
assert f"MOVED = {{ {moved} }}" in chart_js, "a change is worth mentioning at the same size"
point = {"wpm": 120, "fillers": 2.1, "pauses": 6, "lead_in": 1}
assert picture.panels([point], ["a", "b"], point)[:4] == b"\x89PNG"

# ---- after a session: numbers, a chart, and the lessons only if allowed ----
METRICS = {"words": 40, "wpm": 120, "fillers": 1, "pauses": 2, "longest_pause": 1, "lead_in": 1}


def backdate(session: int, minutes: int = 5) -> None:
    """As if it had started `minutes` ago: a session has to last to count."""
    store.db().execute(
        "UPDATE sessions SET started_at = datetime(started_at, ?) WHERE id = ?",
        (f"-{minutes} minutes", session),
    )
    store.db().commit()


one = store.start("talk", "flash-lite", "m", goal=30)
backdate(one)
store.record(one, "interviewer", "How was your day?")
store.record(one, "you", "It was good, I went for a walk.", METRICS)
store.record(one, "you", "Then I cooked dinner for us.", {**METRICS, "fillers": 0})
summary = {"work_on": ["past tense"], "phrases": [{"phrase": "a breath of fresh air",
           "meaning": "something new and pleasant"}], "instead_of_um": ["Let me think"]}  # fmt: skip
store.db().execute("UPDATE sessions SET summary = ? WHERE id = ?", (json.dumps(summary), one))
store.db().commit()
assert today_.streak(today) == 1
now = today_.summary(today)
assert now["sessions"] == 1 and now["last"]["id"] == one and now["streak"] == 1
assert now["work_on"] == ["past tense"] and now["phrases"][0]["phrase"] == "a breath of fresh air"

before = len(sent)
run(reports.after_session(one))
report = sent[-1]
kinds = [b["type"] for b in report["blocks"]]
assert len(sent) == before + 1 and report["title"].startswith("Session done")
assert "of a 30 min goal" in report["title"]
assert kinds[:2] == ["text", "image"] and "fields" not in kinds, "the chart says the numbers"
assert "trend" in report["blocks"][1]["caption"]
assert report["blocks"][0]["text"].startswith("talk · 2 answers")
assert "Since last time" not in report["blocks"][0]["text"], "nothing to compare with yet"
assert "a breath of fresh air" in report["blocks"][-1]["text"]
run(reports.after_session(one))
assert len(sent) == before + 1, "a session is reported once"

# ---- a try is not a session: two answers and two minutes, or it is not counted ----
settings.set("relay_lessons", "off")
two = store.start("talk", "flash-lite", "m")
store.record(two, "you", "Short one.", METRICS)
store.db().execute("UPDATE sessions SET summary = ? WHERE id = ?", (json.dumps(summary), two))
store.db().commit()
before = len(sent)
run(reports.after_session(two))
assert len(sent) == before, "one answer is a try: nothing is sent"
store.record(two, "you", "And a second, quickly.", METRICS)
assert not history.is_counted(two), "two answers, but under two minutes"
assert history.count() == 1 and [s["id"] for s in history.sessions()] == [one]
backdate(two)
assert history.is_counted(two) and history.count() == 2
run(reports.after_session(two))
assert len(sent) == before + 1, "long enough now"
# 2 fillers in 80 words against 1: said in words, since the chart shows only this session
assert "Since last time: 1.2 more fillers per 100 words." in sent[-1]["blocks"][0]["text"]
assert "breath of fresh air" not in json.dumps(sent[-1]), "lessons stay off Telegram"
settings.set("relay_lessons", "on")

# ---- last week's report: after the first session once the week is over ----
before = len(sent)
run(reports.weekly(today))
assert len(sent) == before, "last week had no practice"
run(reports.weekly(today + dt.timedelta(days=7)))  # a week on, this week is last week
weekly = sent[-1]
assert len(sent) == before + 1 and weekly["title"].startswith("Last week: 1 day,")
table = weekly["blocks"][0]
assert table["type"] == "table" and len(table["rows"]) == 7
assert table["rows"][today.weekday()][1] != "-", "today, in its own row"
run(reports.weekly(today + dt.timedelta(days=8)))
assert len(sent) == before + 1, "once a week"

# ---- the study sheet: written by a model, drawn as pages, sent as a PDF ----
from coach import config, layout, llm, sheet  # noqa: E402

for key in ("say", "more"):
    store.record(one, "you", f"One more answer, {key}.", METRICS)
written = {
    "title": "A good session", "went_well": "You told a clear story — well done.",
    "fixes": [{"said": "with me and my wife", "better": "with my wife and me", "why": "polite"}],
    "phrases": [{"phrase": "not really my thing", "meaning": "I don't like it",
                 "instead_of": "I don't like cinema", "example": "Cinemas are not my thing."}],
    "instead_of_um": ["Let me think…"], "practice": ["Retell the film in 60 seconds."] * 3,
}  # fmt: skip


async def model(_ep, messages, max_tokens=None):  # noqa: ARG001 - the real signature
    assert "study sheet" in messages[0]["content"] and "LEARNER:" in messages[1]["content"]
    return llm.Reply(json.dumps(written), 1.0)


llm.patiently = model  # the model is faked by reassigning the one call that reaches it
run(sheet.write(one))
assert sheet.stored(one)["title"] == "A good session"
pdf = sheet.render(one).pdf()
assert pdf[:4] == b"%PDF" and len(sheet.render(one).pngs()) >= 1

# time on the sheet: only what was measured, and a reached goal is good news
timed = {"total": 3000, "hearing": 1000, "thinking": 1500, "voicing": 500}
detail = {
    "minutes": 34.2, "goal_minutes": 30, "averages": {"spoken": 14.6},
    "turns": [{"timing": timed}, {"timing": None}, {"timing": {**timed, "total": 5000}}],
    "listening": {"replies": 20, "helped": 3},
}  # fmt: skip
tiles = sheet._time_tiles(detail)
assert tiles[0] == ("34 min", "session", "goal 30 min, reached", True)
assert tiles[1][0] == "15 min" and tiles[1][2] == "43% of the session"
assert tiles[2][0] == "4.0s"  # the mean of the two timed replies; the untimed one is left out
assert tiles[3][0] == "17/20"
bare = sheet._time_tiles({"minutes": 12, "goal_minutes": None, "averages": {}, "turns": []})
assert bare == [("12 min", "session", "start to last answer", None)]  # nothing invented
assert len(sheet.render(one).pages) >= 2  # the session's answers, charted at the end

relay.remember(f"session:{one}", "")  # report the session again, now with its sheet
before = len(sent)
run(reports.after_session(one))
# Relay's recipe for a file: a line saying what it is, then the file
assert [b["type"] for b in sent[-1]["blocks"]] == ["text", "file"], "the sheet goes as a PDF"
assert sent[-1]["blocks"][1]["filename"].endswith(".pdf")
assert sent[-1]["blocks"][1]["content_type"] == "application/pdf"
assert "breath of fresh air" not in json.dumps(sent[before]), "the sheet carries the lessons"

before = len(sent)
run(reports.after_session(one))
assert len(sent) == before, "a session is reported once, by itself, when it ends"

takes_files = False
relay.remember(f"session:{one}", "")
run(reports.after_session(one))
assert sent[-1]["blocks"][0]["type"] == "image", "an older Relay gets the pages as images"

# long text runs onto a second page; without the font it still renders, in plain ASCII
doc = layout.Doc()
for _ in range(80):
    doc.text("A long line about cinemas, small talk and leftovers — again and again. " * 2)
assert len(doc.pages) >= 2 and doc.pdf()[:4] == b"%PDF"
config.REPORT_FONT = "/nowhere/Inter.ttf"
plain = layout.Doc()
assert plain.plain and plain.clean("café → “ok” — fine") == 'cafe -> "ok" - fine'
assert plain.pdf()[:4] == b"%PDF"

# ---- who it goes to: RELAY_USER, else its old name RELAY_ADMIN, else "admin" ----
os.environ["RELAY_ADMIN"] = "old"
assert relay.recipient() == "old"
os.environ["RELAY_USER"] = "ali"
assert relay.recipient() == "ali"
del os.environ["RELAY_USER"], os.environ["RELAY_ADMIN"]
assert relay.recipient() == "admin"

# ---- switched off without the RELAY_* variables ----
del os.environ["RELAY_API_KEY"]
assert not relay.enabled()

print("ok")
