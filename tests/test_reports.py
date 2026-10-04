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

# ---- Relay itself is faked by reassigning the one function that talks to it ----
sent: list[dict] = []
answers: dict[str, str] = {}


def fake_call(method, path, body=None):
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
assert reports.streak(today) == 1

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

# ---- switched off without the RELAY_* variables ----
del os.environ["RELAY_API_KEY"]
assert not relay.enabled()

print("ok")
