"""The loop behind every conversational mode: the partner speaks, the user answers, repeat.

Not a mode itself - the leading underscore keeps it out of discovery. A mode that is a
conversation supplies its system prompt and its opener and calls `converse`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .. import config, settings

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import Answer, BrowserIO, Retry


async def converse(
    endpoint: Endpoint,
    io: BrowserIO,
    system: Callable[[], str],
    opener: str,
    getting_ready: str = "Getting ready",
    **reply: Any,
) -> None:
    """Run the conversation until the user leaves.

    `system` is called every turn, so the prompt always carries the latest pacing note.
    `reply` is passed through to `io.reply` (a `role`, a `cast` of voices).

    If the model fails, the user's answer stays in the history: tapping "try again"
    re-asks with it, and if they simply speak instead, both answers are sent together.
    """
    # Seeded from the database, so a browser refresh resumes instead of starting over.
    history: list[dict] = io.prior_turns()
    # Owed a reply: a fresh session (the partner opens), or one that died mid-turn.
    said: Answer | Retry | None = io.RETRY if not history or history[-1]["role"] == "user" else None
    if said is None:
        await io.send(type="turn_done")  # resumed on the user's turn: open the mic

    while True:
        if said is not None:
            if said != io.RETRY:
                history.append({"role": "user", "content": said.text})
            turns = history[-settings.get("history_turns") * 2 :]
            # A real conversation opens with a greeting, not with silence.
            opening = not turns
            messages = [{"role": "system", "content": system()}]
            messages += turns or [{"role": "user", "content": opener}]
            spoken = await io.reply(
                endpoint,
                messages,
                thinking=getting_ready if opening else None,
                deadline=config.FIRST_WORD_SECONDS,
                **reply,
            )
            if spoken and spoken.text:
                history.append({"role": "assistant", "content": spoken.text})
        said = await io.answer()
