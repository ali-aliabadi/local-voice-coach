"""shadow - it says a natural sentence, you say it straight back.

Trains the ear and the mouth together: catching every word of connected native speech,
then reproducing its rhythm. Scored by matching words - arithmetic - beside the usual
fluency numbers. A sentence you mostly missed is said again, up to twice.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

from .. import profile

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "repeat natural sentences back, scored word by word"
ENDPOINT = "fast"
PARTNER = "speaker"

PROMPT = (
    "Give one natural sentence a native English speaker might say in everyday conversation, "
    "8 to 16 words, using a common phrasal verb, idiom or contraction. Vary the topic every "
    "time. Output only the sentence."
)
GOOD_ENOUGH = 0.8  # share of words matched to move on to a new sentence
TRIES = 3


def match(target: str, said: str) -> tuple[float, list[str]]:
    """Share of the target's words said back in order, and the ones that were missed."""
    words = lambda text: re.findall(r"[a-z0-9']+", text.lower())  # noqa: E731
    a, b = words(target), words(said)
    if not a:
        return 0.0, []
    blocks = difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks()
    hit = {i for block in blocks for i in range(block.a, block.a + block.size)}
    return len(hit) / len(a), [w for i, w in enumerate(a) if i not in hit]


async def run(endpoint: Endpoint, io: BrowserIO) -> None:
    used: list[str] = []  # so the model does not repeat itself
    sentence, tries = None, 0
    while True:
        if sentence is None:
            ask = "Another sentence, unlike these: " + " | ".join(used[-8:]) if used else "Go."
            messages = [
                {
                    "role": "system",
                    "content": profile.system_prompt("shadow", PROMPT, pacing=False),
                },
                {"role": "user", "content": ask},
            ]
            spoken = await io.reply(endpoint, messages, thinking="Choosing a sentence")
            sentence = spoken.text if spoken and spoken.text else None
            tries = 0
            if sentence:
                used.append(sentence)
        said = await io.answer()
        if sentence is None or said is None or said == io.RETRY:
            continue
        tries += 1
        score, missed = match(sentence, said.text)
        await io.send(
            type="card",
            title=f"{round(score * 100)}% of the words",
            rows=[["it said", sentence], ["you said", said.text]],
            text=f"Missed: {', '.join(missed)}" if missed else "Every word.",
        )
        if score >= GOOD_ENOUGH or tries >= TRIES:
            sentence = None
        else:
            await io.speak(sentence)  # the same sentence again, so "again" replays it too
