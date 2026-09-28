"""talk - one interviewer, fast replies, every answer scored.

Built for reps: the conversation should feel live, so this uses the fast endpoint and
never blocks on anything it does not have to.
"""

from .. import llm, settings, store

HELP = "fast conversation, fluency scored per answer"
ENDPOINT = "fast"

PROMPT = (
    "You are a senior engineer running a realistic but friendly software engineering "
    "interview, spoken out loud. Ask ONE question at a time, in 1-2 short sentences. "
    "Mix behavioural questions ('tell me about a time you...') with technical ones "
    "('how would you design...', 'why did you pick X over Y'). "
    "Always dig into what the candidate actually said with a specific follow-up, "
    "like a real interviewer would. "
    "Never correct their grammar or comment on their English - that breaks their flow. "
    "If they freeze or answer in one line, offer a smaller, easier question instead."
)


OPENER = "Begin the interview. Greet them briefly and ask your first question."


async def run(endpoint, transcriber, io) -> None:
    # Seeded from the database, so a browser refresh resumes instead of starting over.
    history: list[dict] = io.prior_turns()

    if not history:
        # A real interview opens with the interviewer, not with silence.
        await io.send(type="thinking", text="The interviewer is getting ready")
        messages = [
            {"role": "system", "content": settings.prompt("talk", PROMPT)},
            {"role": "user", "content": OPENER},
        ]
        opening = llm.Reply("", None)
        try:
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "sentence":
                    await io.send(type="sentence", text=chunk)
                    await io.say(chunk)
                else:
                    opening = chunk
        except Exception as exc:
            await io.send(type="error", text=await llm.explain(endpoint, exc))
            return
        if opening.text:
            history.append({"role": "assistant", "content": opening.text})
            store.record("interviewer", opening.text, reply_ms=opening.ms)
        await io.send(type="turn_done", latency_ms=opening.ms)

    while True:
        audio = await io.record()
        if audio is None:
            await io.send(type="notice", text="Nothing recorded - hold it a little longer.")
            continue

        text, metrics, words, stt_ms = await transcriber.transcribe(audio)
        if not text:
            await io.send(type="notice", text="Didn't catch that. Move closer to the mic.")
            continue

        turn = io.save_answer(audio, text, metrics, stt_ms)
        await io.send(type="transcript", text=text, metrics=metrics, words=words, turn=turn)

        history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": settings.prompt("talk", PROMPT)}]
        messages += history[-settings.get("history_turns") * 2 :]

        reply = llm.Reply("", None)
        try:
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "sentence":
                    await io.send(type="sentence", text=chunk)
                    await io.say(chunk)
                else:
                    reply = chunk
        except Exception as exc:
            await io.send(type="error", text=await llm.explain(endpoint, exc))
            history.pop()  # don't poison context with an unanswered turn
            continue

        if reply.text:
            history.append({"role": "assistant", "content": reply.text})
            store.record("interviewer", reply.text, reply_ms=reply.ms)
        await io.send(type="turn_done", latency_ms=reply.ms)
        await io.drain()
