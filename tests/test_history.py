"""Profile, session history and progress. Run: python tests/test_history.py"""

import json
import pathlib
import sqlite3
import tempfile

from coach import config  # noqa: I001

config.DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "history.db")

from coach import coach, history, profile, settings, store  # noqa: E402

METRICS = {"words": 20, "wpm": 110, "fillers": 3, "pauses": 2, "longest_pause": 1.4, "lead_in": 2.2}
WORDS = [
    {"word": "So", "start": 2.2, "end": 2.4, "filler": False, "pause": 0.0},
    {"word": "um", "start": 2.4, "end": 2.9, "filler": True, "pause": 0.0},
    {"word": "Redis", "start": 3.8, "end": 4.2, "filler": False, "pause": 0.9},
]

# ---- profile ----
assert not profile.is_set()
assert profile.as_prompt() == ""  # nothing filled in, so the model gets no blanks to guess at

profile.save(
    {
        "name": "Ali",
        "role": "Backend engineer",
        "seniority": "mid-level",
        "focus": "System design.",
        "nonsense": "ignored",
    }
)
assert profile.is_set()
prompt = profile.as_prompt()
assert "Ali" in prompt and "Backend engineer" in prompt and "System design." in prompt
assert "nonsense" not in prompt and "ignored" not in prompt  # unknown keys are dropped
# empty fields must not appear at all, or the model speculates about the blanks
assert "Years of experience" not in prompt
assert "Never read this back" in prompt  # it must not recite the profile at the candidate

full = profile.system_prompt("talk", "BASE PROMPT")
assert full.startswith("BASE PROMPT") and "Ali" in full
# plain conversation keeps their name but not the engineering, or every chat drifts back to it
chat = profile.system_prompt("talk", "BASE PROMPT", interview=False)
assert "Ali" in chat and "Backend engineer" not in chat and "System design." not in chat

settings.set_prompt("talk", "MY OWN PROMPT")
assert profile.system_prompt("talk", "BASE PROMPT").startswith("MY OWN PROMPT")
settings.set_prompt("talk", "")

# the pacing note must exist but must forbid commenting on speech
note = profile.coaching_note({"answers": 9, "wpm": 105, "fillers": 4.2, "lead_in": 3.1})
assert "105" in note and "4.2" in note
assert "Never mention these numbers" in note and "Never correct their English" in note
assert profile.coaching_note({}) == "" and profile.coaching_note(None) == ""
assert "For pacing only" not in profile.system_prompt("talk", "X", pacing=False)

# ---- empty history ----
assert history.sessions() == []
assert history.detail(1) is None
assert history.recent() == {}
assert history.totals()["answers"] == 0

# ---- one full session ----
first = store.start("talk", "flash-lite", "gemini-3.5-flash-lite")
store.record(first, "interviewer", "Tell me about yourself.", reply_ms=900.0)
answer = store.record(first, "you", "So um Redis", METRICS, stt_ms=700, word_rows=WORDS)
store.record(first, "interviewer", "Why Redis?", reply_ms=1100.0)
store.finish(first)

rows = history.sessions()
assert len(rows) == 1 and rows[0]["answers"] == 1 and rows[0]["wpm"] == 110

detail = history.detail(first)
assert detail["answers"] == 1
assert [t["role"] for t in detail["turns"]] == ["interviewer", "you", "interviewer"]
# the per-word data survives, so an old session still shows its highlighted fillers
spoken = detail["turns"][1]
assert [w["word"] for w in spoken["word_rows"] if w["filler"]] == ["um"]
assert detail["turns"][0]["word_rows"] == []  # the interviewer has none
assert detail["averages"]["lead_in"] == 2.2
assert detail["averages"]["fillers"] == 15.0  # 3 fillers in 20 words
assert spoken["fillers"] == 15.0  # each answer is shown as a rate as well

# the session clock and the per-answer series the practice page draws
assert detail["goal_minutes"] is None and detail["minutes"] >= 0
assert round(detail["averages"]["spoken"], 3) == round(20 / 110, 3)  # 20 words at 110 wpm
assert [a["fillers"] for a in history.answers(first)] == [15.0]
assert history.so_far(first)["wpm"] == 110
assert 0 <= store.elapsed(first) < 60
goaled = store.start("talk", "flash-lite", "m", goal=30)
assert store.goal(goaled) == 30 and store.goal(first) is None

# ---- the coach: notes parse however the model wraps them, and repeats are counted ----
assert coach.parse('```json\n{"fixes": []}\n```') == {"fixes": []}
assert coach.parse('Sure! Here you go: {"praise": "clear"} Hope it helps.') == {"praise": "clear"}
assert coach.parse("no json at all") is None and coach.parse("") is None
kinds = {"fixes": [{"kind": "articles"}, {"kind": "articles"}, {"kind": "tense"}]}
store.db().execute("UPDATE turns SET notes = ? WHERE id = ?", (json.dumps(kinds), answer))
store.db().commit()
assert history.mistakes() == [("articles", 2), ("tense", 1)]
assert history.detail(first)["turns"][1]["notes"]["fixes"][1]["kind"] == "articles"
assert history.detail(first)["summary"] is None
# the coach's recap is what the next conversation remembers
recap = {"recap": "They watched Se7en at home with their wife.", "answers": 1}
store.db().execute("UPDATE sessions SET summary = ? WHERE id = ?", (json.dumps(recap), first))
store.db().commit()
assert "Se7en" in profile.system_prompt("talk", "X", interview=False, memory=True)
assert "Se7en" not in profile.system_prompt("roleplay", "X", interview=False)  # asked for

# ---- listening: replies you needed help to follow ----
assert history.listening("", "", first) == {"replies": 0, "helped": 0}  # never tracked
reply = store.record(first, "interviewer", "And then?", reply_ms=1.0)
store.helped(reply, ["text", "again"])
by_ear = store.record(first, "interviewer", "Nice.", reply_ms=1.0)
store.helped(by_ear, [])
assert history.listening("", "", first) == {"replies": 2, "helped": 1}
day = store.db().execute("SELECT substr(at, 1, 10) FROM turns LIMIT 1").fetchone()[0]
assert history.listening(day, day)["helped"] == 1

# ---- a second session, and the totals across both ----
second = store.start("review", "bonsai27", "prism-ml/bonsai-27b")
store.record(
    second,
    "you",
    "second answer",
    {**METRICS, "words": 30, "wpm": 130, "fillers": 1, "lead_in": 1.0},
)
store.record(second, "review", "3/5. Too vague.", reply_ms=8000.0)
store.finish(second)

assert [s["mode"] for s in history.sessions()] == ["review", "talk"]  # newest first
newest = history.sessions()[0]["id"]
assert [s["mode"] for s in history.sessions(before=newest)] == ["talk"]  # the next page
totals = history.totals()
assert totals["sessions"] == 2 and totals["answers"] == 2 and totals["words"] == 50
# weighted by words: 50 words over 20/110 + 30/130 minutes, not the plain mean of 120
assert round(totals["wpm"], 1) == 121.2
assert totals["fillers"] == 8.0  # 4 fillers in 50 words is 8 per 100, however they split
assert history.recent()["answers"] == 2
assert round(history.recent(limit=1)["fillers"], 2) == 3.33  # 1 in 30 words, newest only

# rates, not counts: the same fillers in a longer answer is better, not equal
short = history.rates({"words": 10, "wpm": 120, "fillers": 2, "pauses": 1})
long = history.rates({"words": 100, "wpm": 120, "fillers": 2, "pauses": 1})
assert short["fillers"] == 20.0 and long["fillers"] == 2.0
assert long["pauses"] == 1.2  # one pause in 100 words at 120 wpm: 50 seconds of speech

# a session with no answers is not a session worth listing
empty = store.start("talk", "flash-lite", "m")
store.record(empty, "interviewer", "hello?", reply_ms=100.0)
store.finish(empty)
assert len(history.sessions()) == 2

# ---- the column migration, on a database that predates it ----
old = pathlib.Path(tempfile.mkdtemp()) / "old.db"
bare = store.SCHEMA
for column in ("    words         INTEGER,\n", "    word_rows     TEXT"):
    bare = bare.replace(column, "")
bare = bare.replace("audio_path    TEXT,", "audio_path    TEXT")
connection = sqlite3.connect(old)
connection.executescript(bare)
connection.commit()
connection.close()

config.DB_PATH = str(old)
store._db = None
migrated = store.start("talk", "flash-lite", "m")
assert store.record(migrated, "you", "migrated", METRICS, word_rows=WORDS) is not None
assert history.totals()["words"] == 20  # the added column is written and read back

print("ok")
