"""review - one hard question at a time, then a written technical critique.

Deliberately slow. Latency does not matter here, so it uses the deep endpoint and asks for
the depth a real interviewer would probe. The question is spoken; the critique is written,
because nobody wants to listen to six paragraphs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .. import llm, profile, settings

if TYPE_CHECKING:
    from ..llm import Endpoint
    from ..server.session import BrowserIO

HELP = "one hard question, then a written critique"
ENDPOINT = "deep"
UNLOCK = 2  # an interview: once everyday talk has had two sessions

PROMPT = (
    "You are a staff engineer interviewing a candidate for a software engineering role. "
    "Ask ONE substantial technical question, in 1-2 short spoken sentences. "
    "Prefer questions with real depth behind them - system design, trade-offs, failure "
    "modes, debugging a production incident - over trivia. "
    "If there is history, follow the thread the candidate opened rather than changing topic. "
    "Output only the question."
)

CRITIQUE_PROMPT = (
    "You are a staff engineer who just heard a candidate answer an interview question. "
    "Write a direct, specific critique. Be honest - flattery wastes their time.\n\n"
    "Use these headings:\n"
    "1. Verdict - one line, and a score out of 5.\n"
    "2. What was right - name the specific claims that held up.\n"
    "3. What was wrong, missing or vague - quote their words where useful.\n"
    "4. What a real interviewer would ask next to probe the weak spot.\n"
    "5. A stronger answer, in 3-4 sentences they could actually say.\n\n"
    "Judge the engineering, not the English. Never correct grammar or vocabulary. "
    "The delivery numbers are given only so you can mention pacing or hesitation in the "
    "verdict line if something stands out; ignore them otherwise."
)


async def run(endpoint: Endpoint, io: BrowserIO) -> None:
    history: list[dict] = io.prior_turns()
    question = None

    while True:
        # --- ask, unless a question is still waiting for its answer ---
        if question is None:
            messages = [{"role": "system", "content": profile.system_prompt("review", PROMPT)}]
            messages += history[-settings.get("history_turns") * 2 :]
            asked = await io.reply(endpoint, messages, thinking="Composing a question")
            question = asked.text if asked and asked.text else None

        # --- answer: a failed recording keeps the same question ---
        said = await io.answer()
        if question is None or said is None or said == io.RETRY:
            continue

        # --- critique ---
        delivery = ", ".join(f"{k} {v}" for k, v in (said.metrics or {}).items())
        await io.send(type="thinking", text="Reviewing your answer")
        try:
            critique = await llm.complete(
                endpoint,
                [
                    {
                        "role": "system",
                        "content": profile.system_prompt(
                            "review:critique_prompt", CRITIQUE_PROMPT, pacing=False
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Question asked:\n{question}\n\n"
                        f"Candidate's answer:\n{said.text}\n\n"
                        f"Delivery numbers: {delivery or 'not measured'}",
                    },
                ],
            )
        except Exception as exc:
            await io.send(type="error", text=await llm.explain(endpoint, exc))
            question = None
            continue

        if not critique.text:
            await io.send(
                type="notice",
                text=(
                    "The model returned nothing - a thinking model probably spent the whole "
                    "budget reasoning. Raise 'Review max tokens' in Settings."
                ),
            )
        else:
            await io.send(type="critique", text=critique.text, latency_ms=critique.ms)
            io.save_turn("review", critique.text, critique.ms)
            history.append({"role": "user", "content": f"Q: {question}\nA: {said.text}"})
            history.append({"role": "assistant", "content": critique.text[:400]})
        question = None
