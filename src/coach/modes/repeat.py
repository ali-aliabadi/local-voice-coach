"""repeat - the 4/3/2 drill: the same topic three times, with less time each round.

A classic fluency exercise from language teaching. By the third telling the content is
settled, so the effort goes into saying it smoothly - and the numbers usually show it.
Scripted: the topics are a list and the comparison is arithmetic, so no model is called.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from .. import history, picture
from ._topics import TOPICS

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "one topic three times, faster each time (the 4/3/2 drill)"
ENDPOINT = "fast"  # the contract asks for one; this mode never calls it
PARTNER = "coach"

ROUNDS = (90, 60, 45)  # seconds per telling
LABELS = {
    "wpm": "words per minute",
    "fillers": "fillers per 100 words",
    "pauses": "pauses per minute",
    "lead_in": "seconds before you started",
}


def table(tries: list[dict]) -> list[list[str]]:
    show = lambda key, v: "-" if v is None else f"{v:.0f}" if key == "wpm" else f"{v:.1f}"  # noqa: E731
    head = ["", *(f"telling {n}" for n in range(1, len(tries) + 1))]
    return [head] + [[LABELS[k], *(show(k, t.get(k)) for t in tries)] for k in LABELS]


def change(first: dict, last: dict) -> str:
    """First telling against the last, in words. Only what moved more than noise."""
    said = picture.shifts(first, last)
    if not said:
        return "About the same each time. Next round, aim for smoother, not just faster."
    return "From the first telling to the last: " + ", ".join(said) + "."


async def run(_endpoint: Endpoint, io: BrowserIO) -> None:
    pick = random.Random(io.session)
    while True:
        topic = pick.choice(TOPICS)
        tries: list[dict] = []
        for n, seconds in enumerate(ROUNDS, 1):
            line = (
                f"Your topic: {topic}. Talk about it for up to {seconds} seconds, "
                "starting whenever you are ready."
                if n == 1
                else f"Now tell me the same thing again, in {seconds} seconds this time."
            )
            await io.speak(line)
            while True:
                await io.send(type="limit", seconds=seconds)
                said = await io.answer()
                if said is not None and said != io.RETRY:
                    break
            tries.append(history.rates(said.metrics or {}))
        verdict = change(tries[0], tries[-1])
        await io.send(
            type="card", title=f"Three tellings: {topic}", rows=table(tries), text=verdict
        )
        await io.speak("Have a look at how the three compare. Here comes a new topic.")
