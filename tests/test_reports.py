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
os.environ.update(RELAY_URL="https://relay.test", RELAY_API_KEY="rk_test", RELAY_APP="coach")

from coach import picture, relay, reports, settings, store  # noqa: E402
from coach import today as today_  # noqa: E402

# ---- Relay itself is faked by reassigning the one function that talks to it ----
sent: list[dict] = []
answers: dict[str, str] = {}
takes_files = True  # an older Relay refuses the file block


def fake_call(method, path, body=None):
    files = [b for b in (body or {}).get("blocks", []) if b["type"] == "file"]
    if method == "POST" and not takes_files and files:
        raise RuntimeError("relay 422 invalid_request blocks[0].type: unknown")
    if method == "POST":
        sent.append(body)
        return {"id": f"msg_{len(sent)}", "status": "queued"}
    found = re.match(r"/v1/messages/(.+)/answers", path)
    pressed = answers.get(found.group(1))
    return {"answers": [{"recipient": "ali", "answer": pressed}] if pressed else []}


relay._call = fake_call
run = asyncio.run
today = dt.date.today()
at = lambda hh, mm: dt.datetime.combine(today, dt.time(hh, mm))  # noqa: E731

# ---- the charts on a phone use the same scales as the charts in the app ----
chart_js = (pathlib.Path(__file__).parents[1] / "web" / "chart.js").read_text()
for key, (_, domain, goal) in picture.SERIES.items():
    found = re.search(rf"{key}: \{{\s*label: \"[^\"]*\", domain: \[([^\]]*)\], goal: \[([^\]]*)\]",
                      chart_js)  # fmt: skip
    assert found, f"{key} missing from chart.js"
    parse = lambda text: tuple(float(v) for v in text.split(","))  # noqa: E731
    assert parse(found.group(1)) == domain and parse(found.group(2)) == goal, key
point = {"wpm": 120, "fillers": 2.1, "pauses": 6, "lead_in": 1}
assert picture.panels([point], ["a", "b"], point)[:4] == b"\x89PNG"

# ---- the daily reminder: on time, once, and it listens to the buttons ----
run(reports.remind(at(18, 0)))
assert sent == [], "not before the reminder time"
run(reports.remind(at(19, 5)))
assert len(sent) == 1 and sent[0]["blocks"][-1]["options"] == [reports.NOW, reports.LATER,
                                                               reports.SKIP]  # fmt: skip
assert sent[0]["source"] == "coach" and sent[0]["to"] == ["admin"]
run(reports.remind(at(19, 15)))
assert len(sent) == 1, "no answer yet: wait, never nag"
answers["msg_1"] = reports.LATER
run(reports.remind(at(19, 25)))  # reads the answer
run(reports.remind(at(19, 45)))
assert len(sent) == 1, "snoozed for 30 minutes"
run(reports.remind(at(20, 0)))
assert len(sent) == 2, "asked again after the snooze"
answers["msg_2"] = reports.SKIP
run(reports.remind(at(20, 10)))
run(reports.remind(at(22, 0)))
assert len(sent) == 2, "skip today means today"

# ---- after a session: numbers, a chart, and the lessons only if allowed ----
METRICS = {"words": 40, "wpm": 120, "fillers": 1, "pauses": 2, "longest_pause": 1, "lead_in": 1}
one = store.start("talk", "flash-lite", "m", goal=30)
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
assert kinds[:3] == ["text", "fields", "image"], kinds
assert "a breath of fresh air" in report["blocks"][-1]["text"]
run(reports.after_session(one))
assert len(sent) == before + 1, "a session is reported once"

settings.set("relay_lessons", "off")
two = store.start("talk", "flash-lite", "m")
store.record(two, "you", "Short one.", METRICS)
store.db().execute("UPDATE sessions SET summary = ? WHERE id = ?", (json.dumps(summary), two))
store.db().commit()
run(reports.after_session(two))
assert "breath of fresh air" not in json.dumps(sent[-1]), "lessons stay off Telegram"
settings.set("relay_lessons", "on")

# ---- the weekly report: once a week, every day of it ----
reports.WEEKLY_DAY = today.weekday()  # make today the report day
before = len(sent)
run(reports.weekly(at(19, 0)))
assert len(sent) == before, "not before the evening"
run(reports.weekly(at(21, 0)))
weekly = sent[-1]
assert len(sent) == before + 1 and weekly["title"].startswith("Your week: 1 day,")
table = weekly["blocks"][0]
assert table["type"] == "table" and len(table["rows"]) == 7 and table["rows"][-1][1] != "-"
run(reports.weekly(at(22, 0)))
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
