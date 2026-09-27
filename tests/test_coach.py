"""Run: python test_coach.py"""

from dataclasses import dataclass

from coach.llm import ready_to_speak
from coach.modes.panel import split_speaker
from coach.stt import fluency


@dataclass
class W:
    """Stands in for faster-whisper's Word."""

    start: float
    end: float
    word: str


def say(*triples):
    return [W(start, end, word) for word, start, end in triples]


# ---- sentence chunking ----
assert ready_to_speak("Hello there.")
assert ready_to_speak("Really?")
assert not ready_to_speak("Hel")
assert not ready_to_speak("Hello there")
assert not ready_to_speak("It costs 3.5")
assert not ready_to_speak("Ask Dr.")
assert ready_to_speak("word " * 40)
assert ready_to_speak("line one\n")

# ---- fluency ----
assert fluency([]) is None

solo = fluency(say(("yes", 0.5, 0.9)))
assert solo["words"] == 1 and solo["longest_pause"] == 0.0

smooth = fluency(say(("I", 0.0, 0.5), ("built", 0.5, 1.0), ("a", 1.0, 1.5), ("service", 1.5, 2.0)))
assert smooth["wpm"] == 120, smooth
assert smooth["pauses"] == 0 and smooth["fillers"] == 0 and smooth["lead_in"] == 0.0

hesitant = fluency(
    say(("Um,", 0.0, 0.4), ("mmmm", 0.4, 1.0), ("uh", 1.0, 1.4), ("Redis", 1.4, 2.0))
)
assert hesitant["fillers"] == 3, hesitant
assert fluency(say(("umbrella", 0.0, 0.5), ("humming", 0.5, 1.0)))["fillers"] == 0

gappy = fluency(say(("So", 0.0, 0.3), ("I", 2.0, 2.2), ("used", 2.3, 2.6), ("Postgres", 2.7, 3.2)))
assert gappy["pauses"] == 1 and gappy["longest_pause"] == 1.7, gappy

assert fluency(say(("Well", 3.4, 3.8), ("yes", 3.8, 4.1)))["lead_in"] == 3.4

# ---- panel speaker routing ----
assert split_speaker("MAYA: Tell me about yourself.") == ("MAYA", "Tell me about yourself.")
assert split_speaker("  DEREK:   Why Redis?") == ("DEREK", "Why Redis?")
# unknown name -> no voice, but the prefix is still stripped so it isn't spoken aloud
assert split_speaker("BOB: hello") == (None, "hello")
# no prefix at all -> text untouched
assert split_speaker("Tell me about yourself.") == (None, "Tell me about yourself.")
# a colon mid-sentence must not be mistaken for a speaker tag
assert split_speaker("So the trade-off is: latency versus cost.")[0] is None


# ---- store: persistence and measured latency ----
import pathlib
import tempfile

from coach import config, store

config.DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "t.db")
store._db = None

assert store.measured_latency() == {}
assert store.trend() == []

store.start("talk", "flash-lite", "gemini-3.5-flash-lite")
store.record(
    "you",
    "first answer",
    {"wpm": 100, "fillers": 4, "pauses": 3, "longest_pause": 2.0, "lead_in": 3.0},
    stt_ms=800,
)
store.record("interviewer", "why?", reply_ms=1000.0)
store.record("interviewer", "and then?", reply_ms=2000.0)
store.finish()

# mean of 1000 and 2000, from 2 samples
assert store.measured_latency() == {"flash-lite": (1500.0, 2)}, store.measured_latency()
# only 'you' turns with metrics count as answers
assert len(store.session_scores()) == 1
assert store.session_scores()[0]["fillers"] == 4

# a second session on a different backend is tracked separately
store.start("review", "bonsai27", "prism-ml/bonsai-27b")
store.record(
    "you",
    "second answer",
    {"wpm": 130, "fillers": 1, "pauses": 1, "longest_pause": 0.8, "lead_in": 1.0},
)
store.record("review", "critique text", reply_ms=9000.0)
store.finish()

latency = store.measured_latency()
assert latency["flash-lite"] == (1500.0, 2) and latency["bonsai27"] == (9000.0, 1), latency
assert store.session_scores()[0]["wpm"] == 130  # scoped to the current session
trend = store.trend()
assert len(trend) == 2 and trend[0]["mode"] == "talk" and trend[1]["mode"] == "review"
assert trend[1]["fillers"] == 1.0

# ---- backends: role filtering and availability reasons ----
from coach import backends

fast_keys = {b.key for b, _ in backends.survey("fast")[0]}
deep_keys = {b.key for b, _ in backends.survey("deep")[0]}
assert "flash-lite" in fast_keys and "flash-lite" not in deep_keys
assert "bonsai27" in deep_keys and "bonsai27" not in fast_keys
assert "flash" in fast_keys and "flash" in deep_keys  # declared for both roles

backends.online = lambda _timeout=2.0: False
backends.lm_studio_models = lambda _timeout=1.5: set()
rows, any_available = backends.survey("fast")
assert not any_available
assert all(why for _, why in rows)
assert any(why == "no internet" for _, why in rows)

print("ok")
