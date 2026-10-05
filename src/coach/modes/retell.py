"""retell - it tells a short story, you tell it back in your own words.

Listening and speaking in one exercise: you have to catch the story first, then rebuild
it out loud. The partner says what you got and, gently, one thing you missed - about
understanding only, never grammar.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import profile
from ._converse import converse

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "it tells a short story, you retell it in your own words"
ENDPOINT = "fast"
PARTNER = "storyteller"

PROMPT = (
    "You help someone practise listening and speaking English. Each round, tell a short "
    "everyday story out loud - 60 to 90 words, 4 to 6 sentences, with a clear order of "
    "events and two or three concrete details such as a name, a place or a time - then ask "
    "them to tell it back in their own words.\n\n"
    "When they retell it, react in 1-2 warm sentences: name something they got right and, "
    "gently, one detail they missed or mixed up. Then tell a new, different story. Vary the "
    "topics: work, travel, family, neighbours, food, small accidents, good luck. Use natural "
    "spoken English with common phrasal verbs. Judge only whether they understood - never "
    "their grammar. Everything you write is read aloud: no lists, no emoji."
)
OPENER = "Greet them in one sentence, then tell the first story."
STORY_TOKENS = 400  # a story and a reaction do not fit the conversational default


async def run(endpoint: Endpoint, io: BrowserIO) -> None:
    await converse(
        endpoint,
        io,
        lambda: profile.system_prompt("retell", PROMPT, interview=False),
        OPENER,
        getting_ready="Thinking of a story",
        max_tokens=STORY_TOKENS,
    )
