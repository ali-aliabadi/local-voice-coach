"""How long an answer to the question just asked should take, decided per question.

A fixed limit was wrong both ways: 90 seconds cuts a system design answer off half way,
and lets "why do you want this job" ramble. A real interviewer's patience depends on what
they asked, so the model that asks sets the budget, in the same reply: it writes "[60]"
beside its question, and `BrowserIO.reply` takes the tag out before anything is spoken.
One request a turn, not two - free tiers count requests. The model cannot judge while
the user speaks, since it only sees the words after they stop, so it decides when it
asks, and the page counts down. The `answer_limit` setting is the ceiling, and the
fallback when the model leaves the tag out.
"""

from __future__ import annotations

from .. import settings

SHORTEST = 15  # seconds; below this no real answer fits
INSTRUCTION = (
    "\n\nBegin every reply with how many seconds a strong, concise spoken answer to your "
    "question should take, in square brackets, for example [60]. As a guide: a quick "
    "clarification 20, tell me about yourself 60, a follow-up on a project 45-90, a "
    "behavioural story 90-120, a system design walk-through 180-300. The number is never "
    "read aloud. If they talk past it they are stopped, and you will be told."
)


def seconds(asked: int | None, on: bool) -> int:
    """The countdown for the next answer: the model's number within bounds, 0 for none."""
    ceiling = settings.get("answer_limit") if on else 0
    if ceiling <= 0:
        return 0
    if asked is None:
        return ceiling
    return max(SHORTEST, min(asked, ceiling))
