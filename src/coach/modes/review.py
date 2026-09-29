"""review - one hard question at a time, then a written technical critique.

Deliberately slow. Latency does not matter here, so it uses the deep endpoint and asks for
the depth a real interviewer would probe. The question is spoken; the critique is written,
because nobody wants to listen to six paragraphs.
"""

from .. import llm, profile, settings, store

HELP = "one hard question, then a written critique"
ENDPOINT = "deep"

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


async def run(endpoint, transcriber, io) -> None:
    history: list[dict] = io.prior_turns()

    while True:
        # --- ask ---
        messages = [{"role": "system", "content": profile.system_prompt("review", PROMPT)}]
        messages += history[-settings.get("history_turns") * 2 :]
        await io.send(type="thinking", text="Composing a question")
        asked = llm.Reply("", None)
        try:
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "sentence":
                    await io.send(type="sentence", text=chunk)
                    await io.say(chunk)
                else:
                    asked = chunk
        except Exception as exc:
            await io.send(type="error", text=await llm.explain(endpoint, exc))
            return
        question = asked.text
        store.record("interviewer", question, reply_ms=asked.ms)
        await io.send(type="turn_done", latency_ms=asked.ms)
        await io.drain()

        # --- answer ---
        audio = await io.record()
        if audio is None:
            await io.send(type="notice", text="Nothing recorded - hold it a little longer.")
            continue
        text, metrics, words, stt_ms = await transcriber.transcribe(audio)
        if not text:
            await io.send(type="notice", text="Didn't catch that. Move closer to the mic.")
            continue

        turn = io.save_answer(audio, text, metrics, stt_ms, words)
        await io.send(type="transcript", text=text, metrics=metrics, words=words, turn=turn)

        # --- critique ---
        delivery = ", ".join(f"{k} {v}" for k, v in (metrics or {}).items()) or "not measured"
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
                        "content": f"Question asked:\n{question}\n\nCandidate's answer:\n{text}\n\n"
                        f"Delivery numbers: {delivery}",
                    },
                ],
            )
        except Exception as exc:
            await io.send(type="error", text=await llm.explain(endpoint, exc))
            continue

        if not critique.text:
            await io.send(
                type="notice",
                text=(
                    "The model returned nothing - a thinking model probably spent the whole "
                    "budget reasoning. Raise 'Review max tokens' in Settings."
                ),
            )
            continue

        await io.send(type="critique", text=critique.text, latency_ms=critique.ms)
        store.record("review", critique.text, reply_ms=critique.ms)
        history.append({"role": "user", "content": f"Q: {question}\nA: {text}"})
        history.append({"role": "assistant", "content": critique.text[:400]})
