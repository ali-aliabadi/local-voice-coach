"""scenario - you describe the interview, then it plays that interviewer.

Its first turn asks for the scenario - the role, the company, the kind of interview, who
the interviewer is - and your first answer is it. Describing it is spoken practice too, so
there is no form to fill in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import profile
from ._converse import converse
from .interview import clock

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "you describe the interview, it plays the interviewer"
ENDPOINT = "fast"
UNLOCK = 2  # an interview: once everyday talk has had two sessions
INTERVIEW = True

# ponytail: the scenario is only the first answer in the history, so it leaves the window
# after `history_turns` exchanges (50 by default, over an hour); pin it if that bites.
PROMPT = (
    "You run a spoken mock interview on a scenario the candidate chooses. Your first turn "
    "asked them to describe it, and their first answer is the scenario. Once you have it, "
    "become that interviewer and run the interview the way that kind of interview really "
    "runs, start to finish. If they leave details out, fill them in plausibly and keep them "
    "consistent; ask back only if you cannot start without it. Where the scenario and the "
    "resume or job posting disagree, the scenario wins.\n\n"
    "Ask one question per turn, in 1-3 short spoken sentences. React briefly, the way a "
    "person does, but do not praise every answer. If an answer is vague, ask for specifics. "
    "Stay in character. Never correct their English or comment on how they speak. "
    "Everything you write is read aloud: no lists, no emoji, no stage directions."
)
OPENER = (
    "Greet them in one sentence, then ask them to describe the interview they want to "
    "practise: the role and the company, the kind of interview, and who you should be. "
    "Do not start the interview yet."
)


async def run(endpoint: Endpoint, io: BrowserIO) -> None:
    await converse(
        endpoint,
        io,
        lambda: profile.system_prompt("scenario", PROMPT) + clock(io.session),
        OPENER,
    )
