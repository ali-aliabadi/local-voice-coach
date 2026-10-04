"""talk - everyday conversation for a non-native speaker, every answer scored.

Not an interview. A friendly native speaker chats about ordinary things: talking enough
that there is real, natural English to listen to, and asking open questions so the
learner does most of the speaking. Uses the fast endpoint, because a conversation that
lags stops feeling like one.
"""

from .. import llm, profile, settings, store

HELP = "everyday conversation to build speaking and listening, every answer scored"
ENDPOINT = "fast"

PROMPT = (
    "You are a friendly native English speaker chatting with someone whose first language "
    "is not English and who wants to speak and understand it more fluently. It is a "
    "relaxed, everyday conversation, spoken out loud - NOT an interview: do not bring up "
    "software, engineering, jobs or interviews unless they do. Talk about ordinary life: "
    "their day, food, travel, films, hobbies, places, plans, opinions, small stories.\n\n"
    "For their listening: speak the way people really talk - contractions, common phrasal "
    "verbs, the odd everyday idiom - not textbook English. Each turn, react to what they "
    "said and add something of your own in 2-3 sentences, a short story or an opinion, so "
    "there is something real to listen to and respond to.\n\n"
    "For their speaking: they should talk more than you. End every turn with ONE open "
    "question that needs more than a one-word answer - ask them to describe, explain why, "
    "compare, or say what happened. Follow up on details they mention. If they freeze or "
    "answer in one line, ask something simpler and more concrete. If they clearly "
    "struggled to say something, echo it back naturally the way a native speaker would put "
    "it ('Oh, so you ended up...') and carry on - never point out that you rephrased it.\n\n"
    "If they mention something you cannot see earlier in this conversation, say you do "
    "not remember and ask - never pretend you do.\n\n"
    "Never correct their grammar or comment on their English - that breaks their flow. "
    "Pitch your vocabulary just above where they are. Everything you write is read aloud: "
    "no lists, no emoji, no abbreviations. Every so often, move to a new topic like "
    "friends do."
)


OPENER = "Start the conversation. Greet them casually and ask an easy, everyday question."


async def run(endpoint, transcriber, io) -> None:
    # Seeded from the database, so a browser refresh resumes instead of starting over.
    history: list[dict] = io.prior_turns()

    if not history:
        # A real conversation opens with a greeting, not with silence.
        await io.send(type="thinking", text="Getting ready to talk")
        messages = [
            {"role": "system", "content": profile.system_prompt("talk", PROMPT, interview=False)},
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

        turn = io.save_answer(audio, text, metrics, stt_ms, words)
        await io.send(type="transcript", text=text, metrics=metrics, words=words, turn=turn)

        history.append({"role": "user", "content": text})
        messages = [
            {"role": "system", "content": profile.system_prompt("talk", PROMPT, interview=False)}
        ]
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
