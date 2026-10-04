"""Run: python tests/test_coach.py"""

import json
import pathlib
import tempfile
from dataclasses import dataclass

# A scratch database first: fluency() reads its thresholds from settings, which reads
# from SQLite, so this must happen before anything else is imported or called.
from coach import config  # noqa: I001

config.DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "test.db")

from coach import backends, settings, store  # noqa: E402
from coach.llm import conversation, split_for_speech, split_speaker  # noqa: E402
from coach.modes.panel import PANEL  # noqa: E402
from coach.stt import filler_pattern, fluency, word_rows  # noqa: E402


@dataclass
class W:
    """Stands in for faster-whisper's Word."""

    start: float
    end: float
    word: str


def say(*triples):
    return [W(start, end, word) for word, start, end in triples]


# ---- sentence chunking ----
# Models stream several words per token, so a sentence boundary usually arrives in the
# middle of a token. Splitting only when the buffer *ended* on a boundary missed those,
# and the length cap then cut sentences in half - the interviewer audibly stopped
# mid-sentence. Feed tokens the way a model really sends them.
def stream(tokens):
    buffer, spoken = "", []
    for token in tokens:
        buffer += token
        speak, buffer = split_for_speech(buffer)
        if speak:
            spoken.append(speak)
    tail, _ = split_for_speech(buffer, flush=True)
    if tail:
        spoken.append(tail)
    return spoken


spoken = stream(
    [
        "That sounds",
        " like a really",
        " critical piece of the system to",
        " own. Walk me",
        " through how you handled two requests in the same millisecond?",
    ]
)
assert spoken == [
    "That sounds like a really critical piece of the system to own.",
    "Walk me through how you handled two requests in the same millisecond?",
], spoken

# every chunk must end on a real sentence ending, never mid-sentence
assert all(chunk[-1] in ".!?…" for chunk in spoken), spoken

assert stream(["Hello. How are you? I am fine."]) == ["Hello. How are you? I am fine."]
assert stream(["It costs 3.5 million", " and Dr. Chen signed", " it off."]) == [
    "It costs 3.5 million and Dr. Chen signed it off."
]
assert stream(["Half a sen"]) == ["Half a sen"]  # flushed at the end of the stream
assert split_for_speech("Half a sen") == ("", "Half a sen")  # but not before then
assert split_for_speech("") == ("", "")

# a run-on with no punctuation eventually breaks, but between words, never inside one
run_on = stream([w + " " for w in ["word"] * 90])
assert len(run_on) > 1 and all(" " in c for c in run_on[:-1])
assert not any(c.endswith("wor") or c.startswith("rd") for c in run_on), run_on

# ---- filler matching: a word counts however long it is drawn out ----
pattern = filler_pattern("um uh er ah hmm mm")
for drawn_out in ("um", "ummm", "uhhh", "mmmm", "hmm", "Um"):
    assert pattern.fullmatch(drawn_out), drawn_out
for real_word in ("umbrella", "humming", "Redis", "another"):
    assert not pattern.fullmatch(real_word), real_word
assert not filler_pattern("").fullmatch("um")  # empty list matches nothing, not everything

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

gappy = fluency(say(("So", 0.0, 0.3), ("I", 2.0, 2.2), ("used", 2.3, 2.6), ("Postgres", 2.7, 3.2)))
assert gappy["pauses"] == 1 and gappy["longest_pause"] == 1.7, gappy

assert fluency(say(("Well", 3.4, 3.8), ("yes", 3.8, 4.1)))["lead_in"] == 3.4

# Regression: faster-whisper hands back numpy scalars, which are not JSON serialisable
# and which sqlite3 rejects. Everything leaving fluency() must be a plain Python type.
try:
    import numpy as np

    numpy_words = [
        W(np.float32(0.0), np.float32(0.5), "I"),
        W(np.float32(1.4), np.float32(2.0), "um"),
    ]
    metrics = fluency(numpy_words)
    json.dumps(metrics)  # would raise on int64/float32
    json.dumps(word_rows(numpy_words))
    assert all(type(v) in (int, float) for v in metrics.values()), metrics
except ImportError:
    pass

# ---- word rows drive the highlighted transcript and the timeline ----
rows = word_rows(say(("So", 0.0, 0.3), ("um", 2.0, 2.4), ("Redis", 2.5, 3.0)))
assert [r["word"] for r in rows] == ["So", "um", "Redis"]
assert rows[1]["filler"] and not rows[2]["filler"]
assert rows[1]["pause"] == 1.7  # the gap before this word, since it beats the threshold
assert rows[2]["pause"] == 0.0  # 0.1s gap is below the threshold, so not flagged
assert rows[0]["pause"] == 0.0  # nothing precedes the first word

# ---- message ordering ----
# Local models served by LM Studio render a jinja chat template that rejects anything but
# strict user/assistant alternation after the system message. It broke the moment the
# interviewer started speaking first. Gemini never complained, so only a real local call
# caught it.
SYS = {"role": "system", "content": "sys"}
ASSISTANT = {"role": "assistant", "content": "Tell me about yourself."}
USER = {"role": "user", "content": "I built a payment service."}


def alternates(messages):
    body = [m["role"] for m in messages if m["role"] != "system"]
    return body[0] == "user" and all(a != b for a, b in zip(body, body[1:], strict=False))


assert alternates(conversation([SYS, ASSISTANT, USER]))  # interviewer opened
assert alternates(conversation([SYS, USER, ASSISTANT, USER]))  # already fine
assert alternates(conversation([SYS, USER, USER]))  # two of ours in a row
assert alternates(conversation([SYS, ASSISTANT, USER, ASSISTANT, USER]))  # rebuilt from db
# the interviewer's opening question is kept, not dropped, so context survives
assert any(ASSISTANT["content"] in m["content"] for m in conversation([SYS, ASSISTANT, USER]))
assert len([m for m in conversation([SYS, SYS, USER]) if m["role"] == "system"]) == 1

# ---- panel speaker routing ----
assert split_speaker("MAYA: Tell me about yourself.", PANEL) == ("MAYA", "Tell me about yourself.")
assert split_speaker("  DEREK:   Why Redis?", PANEL) == ("DEREK", "Why Redis?")
assert split_speaker("BOB: hello", PANEL) == (None, "hello")  # unknown name, prefix still stripped
assert split_speaker("Tell me about yourself.", PANEL) == (None, "Tell me about yourself.")
assert split_speaker("So the trade-off is: latency versus cost.", PANEL)[0] is None

# ---- settings ----
assert settings.get("pause_seconds") == 0.6
settings.set("pause_seconds", "0.9")
assert settings.get("pause_seconds") == 0.9  # coerced back to the default's type
assert isinstance(settings.get("history_turns"), int)
settings.set("pause_seconds", 0.6)
# a default is never stored, or saving the form would freeze it and a better one never lands
stored = "SELECT COUNT(*) FROM settings WHERE key = ?"
assert store.db().execute(stored, ("pause_seconds",)).fetchone()[0] == 0
settings.set_prompt("talk", "BUILT-IN", default="BUILT-IN")
assert store.db().execute(stored, ("prompt:talk",)).fetchone()[0] == 0

assert settings.prompt("talk", "BUILT-IN") == "BUILT-IN"
settings.set_prompt("talk", "be brutal")
assert settings.prompt("talk", "BUILT-IN") == "be brutal"
settings.set_prompt("talk", "   ")  # blank means fall back to the mode's own prompt
assert settings.prompt("talk", "BUILT-IN") == "BUILT-IN"

form = {f["key"]: f for f in settings.as_form(voices=("am_puck", "af_heart"))}
assert form["gemini_api_key"]["value"] == ""  # secrets are never sent to the browser
assert form["tts_voice"]["choices"] == ["am_puck", "af_heart"]  # filled at request time
assert form["whisper_model"]["restart"] is True

# ---- store: persistence, latency and retention ----
assert store.measured_latency() == {} and store.trend() == []

one = store.start("talk", "flash-lite", "gemini-3.5-flash-lite")
first = store.record(one, "you", "an answer", smooth, stt_ms=800, audio_path="/tmp/gone.wav")
store.record(one, "interviewer", "why?", reply_ms=1000.0)
store.record(one, "interviewer", "and then?", reply_ms=2000.0)
store.finish(one)

assert store.measured_latency() == {"flash-lite": (1500.0, 2)}
assert len(store.session_scores(one)) == 1
assert store.audio_path(first) == "/tmp/gone.wav"
assert store.purge_audio(7) == 1  # the file is missing, so the row is cleared
assert store.audio_path(first) is None
assert store.purge_audio(0) == 0  # 0 means keep forever

two = store.start("review", "bonsai27", "prism-ml/bonsai-27b")
store.record(two, "you", "second", gappy)
store.record(two, "review", "critique", reply_ms=9000.0)
store.finish(two)
# each session is its own: two tabs no longer file answers under one another
assert len(store.session_scores(one)) == 1 and len(store.session_scores(two)) == 1
assert store.measured_latency()["bonsai27"] == (9000.0, 1)
trend = store.trend()
assert len(trend) == 2 and trend[0]["mode"] == "talk" and trend[1]["mode"] == "review"

store.forget_everything()
assert store.trend() == [] and store.measured_latency() == {}

# ---- backends: role filtering and availability ----
fast_keys = {b.key for b, _ in backends.survey("fast")[0]}
deep_keys = {b.key for b, _ in backends.survey("deep")[0]}
assert "flash-lite" in fast_keys and "flash-lite" not in deep_keys
assert "bonsai27" in deep_keys and "bonsai27" not in fast_keys
assert "flash" in fast_keys and "flash" in deep_keys

backends.online = lambda _timeout=2.0: False
backends.lm_studio_models = lambda _timeout=1.5: set()
rows, any_available = backends.survey("fast")
assert not any_available
assert any(why == "no internet" for _, why in rows)

print("ok")
