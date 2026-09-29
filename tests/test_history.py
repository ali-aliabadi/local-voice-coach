"""Profile, session history and progress. Run: python tests/test_history.py"""

import pathlib
import sqlite3
import tempfile

from coach import config  # noqa: I001

config.DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "history.db")

from coach import history, profile, settings, store  # noqa: E402

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
store.record("interviewer", "Tell me about yourself.", reply_ms=900.0)
answer = store.record("you", "So um Redis", METRICS, stt_ms=700, word_rows=WORDS)
store.record("interviewer", "Why Redis?", reply_ms=1100.0)
store.finish()

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

# ---- a second session, and the totals across both ----
store.start("review", "bonsai27", "prism-ml/bonsai-27b")
store.record(
    "you", "second answer", {**METRICS, "words": 30, "wpm": 130, "fillers": 1, "lead_in": 1.0}
)
store.record("review", "3/5. Too vague.", reply_ms=8000.0)
store.finish()

assert [s["mode"] for s in history.sessions()] == ["review", "talk"]  # newest first
totals = history.totals()
assert totals["sessions"] == 2 and totals["answers"] == 2 and totals["words"] == 50
assert totals["wpm"] == 120  # mean of 110 and 130
assert history.recent()["answers"] == 2
assert history.recent(limit=1)["fillers"] == 1  # only the newest session

# a session with no answers is not a session worth listing
store.start("talk", "flash-lite", "m")
store.record("interviewer", "hello?", reply_ms=100.0)
store.finish()
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
store.start("talk", "flash-lite", "m")
assert store.record("you", "migrated", METRICS, word_rows=WORDS) is not None
assert history.totals()["words"] == 20  # the added column is written and read back

print("ok")
