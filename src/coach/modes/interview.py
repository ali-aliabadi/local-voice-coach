"""interview - one whole interview, the way a real one runs, built on your resume.

One interviewer, start to finish: introductions, "tell me about yourself", a deep dive into
what your resume says you did, a design question in your stack, a behavioural one, then
your questions for them. They are told the time on every turn, so they keep to it the way
a real interviewer watches the clock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import profile, store
from ._converse import converse

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "a whole interview, built on your resume"
ENDPOINT = "fast"
UNLOCK = 2  # an interview: once everyday talk has had two sessions
INTERVIEW = True

MINUTES = 45  # how long a real interview runs, for a session with no goal

PROMPT = (
    "You are a senior software engineer interviewing a candidate for a role on your team. "
    "The interview is spoken out loud. Run it the way a real one runs, in this order:\n"
    "1. Greet them, say who you are, and say briefly how the time will go.\n"
    "2. Ask them to tell you about themselves.\n"
    "3. Go deep on one or two things from their resume. Ask them to walk you through it, "
    "then follow up on what they said - their own part in it, why they chose what they "
    "chose, what went wrong, how they knew it worked. Stay on a topic for several questions "
    "before moving on, as real interviewers do. If you have no resume, dig into the "
    "background they just described instead.\n"
    "4. One technical question about the stack they use: a design or a trade-off, talked "
    "through out loud, no code.\n"
    "5. One behavioural question - a time something went wrong, or a disagreement - "
    "anchored on a role they have had.\n"
    "6. With about five minutes left, ask what questions they have for you, and answer them "
    "in character.\n"
    "7. Close: thank them and tell them what happens next.\n\n"
    "Ask one question per turn, in 1-3 short spoken sentences. React to what they said "
    "briefly, the way a person does, but do not praise every answer. If an answer is vague, "
    "ask for specifics. If you are not given a job posting, invent a plausible company that "
    "fits what they are targeting, and keep it consistent. After the close, if they keep "
    "talking, answer briefly as yourself. Never correct their English or comment on how "
    "they speak. Everything you write is read aloud: no lists, no emoji, no stage directions."
)
OPENER = "Begin the interview."


def clock(session: int) -> str:
    """How far into the interview this is, so it keeps to time."""
    length = store.goal(session) or MINUTES
    gone = round(store.elapsed(session) / 60)
    return f"\n\nTime: {gone} minutes into a {length}-minute interview."


async def run(endpoint: Endpoint, io: BrowserIO) -> None:
    await converse(
        endpoint,
        io,
        lambda: profile.system_prompt("interview", PROMPT) + clock(io.session),
        OPENER,
        getting_ready="Reading your resume" if profile.get("resume").strip() else "Getting ready",
    )
