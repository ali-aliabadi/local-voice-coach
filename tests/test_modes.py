"""What the modes say and hear: chunking a reply for speech, routing a panel's voices, and
the arithmetic behind shadow and repeat. Run: python tests/test_modes.py"""

import pathlib
import tempfile

from coach import config  # noqa: I001

config.DB_PATH = str(pathlib.Path(tempfile.mkdtemp()) / "modes.db")

from coach.chunks import split_for_speech, split_speaker  # noqa: E402
from coach.llm import retry_after  # noqa: E402
from coach.modes import discover, repeat, shadow, state  # noqa: E402
from coach.modes.panel import PANEL  # noqa: E402


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

# ---- the first words of a reply may end at a clause: they are the wait you feel ----
assert split_for_speech("Oh, nice one, getting home", eager=True) == (
    "Oh, nice one,",
    "getting home",
)
assert split_for_speech("Oh, ", eager=True) == ("", "Oh, ")  # too short to sound natural
assert split_for_speech("About 1,000 people came", eager=True)[0] == ""  # not a clause
assert split_for_speech("Oh, nice one, getting home") == ("", "Oh, nice one, getting home")
assert split_for_speech("Done. And then, more", eager=True) == ("Done.", "And then, more")

# ---- shadow: word matching is arithmetic, and order matters ----
assert shadow.match("I ended up staying in", "I ended up staying in") == (1.0, [])
score, missed = shadow.match("I ended up staying in last night", "I end up staying last night")
assert round(score, 2) == 0.71 and missed == ["ended", "in"], (score, missed)
assert shadow.match("", "anything") == (0.0, [])

# ---- repeat: the first telling against the last, in words, noise left out ----
first, last = {"wpm": 100, "fillers": 3.0, "pauses": 6.0}, {"wpm": 118, "fillers": 2.9, "pauses": 4}
assert repeat.change(first, last) == (
    "From the first telling to the last: 18 wpm faster, 2.0 fewer pauses a minute."
)
assert repeat.change(first, first).startswith("About the same")
assert len(repeat.table([first, last])) == 5 and repeat.table([first])[1][1] == "100"

# ---- panel speaker routing ----
assert split_speaker("MAYA: Tell me about yourself.", PANEL) == ("MAYA", "Tell me about yourself.")
assert split_speaker("  DEREK:   Why Redis?", PANEL) == ("DEREK", "Why Redis?")
assert split_speaker("BOB: hello", PANEL) == (None, "hello")  # unknown name, prefix still stripped
assert split_speaker("Tell me about yourself.", PANEL) == (None, "Tell me about yourself.")
assert split_speaker("So the trade-off is: latency versus cost.", PANEL)[0] is None

# ---- rate limits: a per-minute wait is waited out, a daily one is reported ----
assert retry_after("Please retry in 33.876060542s.") == 33.876060542
assert retry_after("Please retry in 3h35m42.5s.") == 3 * 3600 + 35 * 60 + 42.5
assert retry_after("Please retry in 2m.") == 120 and retry_after("no hint") is None

# "high demand" is a 503 that passes: the background queue waits it out, and says so
import asyncio  # noqa: E402
import types  # noqa: E402

import httpx  # noqa: E402
import openai  # noqa: E402

from coach import llm  # noqa: E402

said = []


async def overloaded_once(_ep, _messages, _max_tokens=None):
    if not said:
        response = httpx.Response(503, request=httpx.Request("POST", "http://model"))
        raise openai.InternalServerError("high demand", response=response, body=None)
    return llm.Reply("fine", 1.0)


async def no_wait(_seconds):
    said.append(llm.waiting)


real_complete, real_sleep = llm.complete, asyncio.sleep
llm.complete, asyncio.sleep = overloaded_once, no_wait
try:
    reply = asyncio.run(llm.patiently(types.SimpleNamespace(model="flash"), []))
finally:
    llm.complete, asyncio.sleep = real_complete, real_sleep
assert reply.text == "fine" and said == ["flash is busy, trying again in 30s"], said
assert llm.waiting == "", "cleared once it is past"

# no API key yet: the pages that tell you to add one must still load
assert llm._client("https://model.test", "").api_key

# ---- which modes a beginner sees: talk alone, then all, the interviews last ----
found = discover()
assert [n for n, m in found.items() if state(m, 0) != "hidden"] == ["talk"]
assert {n for n, m in found.items() if state(m, 1) == "locked"} == {"panel", "review"}
assert all(state(m, 2) == "open" for m in found.values())

print("ok")
