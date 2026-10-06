"""panel - two or more interviewers, each with their own voice.

Closer to a real onsite: someone warm, someone digging into technical detail, and someone
pushing back. Kokoro ships 54 voices, so a panel costs nothing extra to run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import profile
from ._converse import converse

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "several interviewers, one voice each"
ENDPOINT = "fast"
UNLOCK = 2  # an interview: once everyday talk has had two sessions
INTERVIEW = True
PARTNER = "panel"

# name -> (kokoro voice, what they care about). Add a row and they join the panel.
PANEL = {
    "MAYA": ("af_heart", "the hiring manager: warm, asks behavioural and motivation questions"),
    "DEREK": ("bm_george", "a staff engineer: digs into system design and technical trade-offs"),
    "PRIYA": ("af_nicole", "the bar raiser: pushes back, asks about edge cases and failure modes"),
}
VOICES = {name: voice for name, (voice, _) in PANEL.items()}

PROMPT = (
    "You are a panel of interviewers running a realistic software engineering interview, "
    "spoken out loud. The panel is:\n"
    + "\n".join(f"- {name}: {role}" for name, (_, role) in PANEL.items())
    + "\n\nExactly ONE panellist speaks per turn. Start every reply with their name and a "
    "colon, like 'MAYA: ...'. Choose whoever most naturally follows what the candidate just "
    "said, and let them hand off to each other like real people do. "
    "Keep each turn to 1-2 short spoken sentences, and always ask one question. "
    "Never correct the candidate's grammar or comment on their English."
)


OPENER = "Begin the interview. One panellist greets them briefly and asks the first question."


async def run(endpoint: Endpoint, io: BrowserIO) -> None:
    await io.send(
        type="panel", members=[{"name": name, "role": role} for name, (_, role) in PANEL.items()]
    )
    await converse(
        endpoint,
        io,
        lambda: profile.system_prompt("panel", PROMPT),
        OPENER,
        getting_ready="The panel is getting ready",
        role="panel",
        cast=VOICES,
    )
