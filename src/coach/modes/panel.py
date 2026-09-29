"""panel - two or more interviewers, each with their own voice.

Closer to a real onsite: someone warm, someone digging into technical detail, and someone
pushing back. Kokoro ships 54 voices, so a panel costs nothing extra to run.
"""

import re

from .. import llm, profile, settings, store

HELP = "several interviewers, one voice each"
ENDPOINT = "fast"

# name -> (kokoro voice, what they care about). Add a row and they join the panel.
PANEL = {
    "MAYA": ("af_heart", "the hiring manager: warm, asks behavioural and motivation questions"),
    "DEREK": ("bm_george", "a staff engineer: digs into system design and technical trade-offs"),
    "PRIYA": ("af_nicole", "the bar raiser: pushes back, asks about edge cases and failure modes"),
}
DEFAULT_VOICE = next(iter(PANEL.values()))[0]
NAME_RE = re.compile(r"^\s*([A-Z][A-Z]+)\s*:\s*")

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


def split_speaker(text: str) -> tuple[str | None, str]:
    """Pull a leading 'NAME:' off the reply. Returns (name or None, remaining text)."""
    match = NAME_RE.match(text)
    if not match:
        return None, text
    name = match.group(1)
    return (name if name in PANEL else None), text[match.end() :].strip()


OPENER = "Begin the interview. One panellist greets them briefly and asks the first question."


async def run(endpoint, transcriber, io) -> None:
    history: list[dict] = io.prior_turns()
    await io.send(
        type="panel", members=[{"name": name, "role": role} for name, (_, role) in PANEL.items()]
    )

    if not history:
        await io.send(type="thinking", text="The panel is getting ready")
        messages = [
            {"role": "system", "content": profile.system_prompt("panel", PROMPT)},
            {"role": "user", "content": OPENER},
        ]
        name, voice, opening = None, DEFAULT_VOICE, llm.Reply("", None)
        try:
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "done":
                    opening = chunk
                    continue
                if name is None:
                    found, chunk = split_speaker(chunk)
                    if found:
                        name, voice = found, PANEL[found][0]
                    if not chunk:
                        continue
                await io.send(type="sentence", text=chunk, speaker=name)
                await io.say(chunk, voice=voice)
        except Exception as exc:
            await io.send(type="error", text=await llm.explain(endpoint, exc))
            return
        if opening.text:
            history.append({"role": "assistant", "content": opening.text})
            store.record(f"panel:{name or '?'}", opening.text, reply_ms=opening.ms)
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
        messages = [{"role": "system", "content": profile.system_prompt("panel", PROMPT)}]
        messages += history[-settings.get("history_turns") * 2 :]

        # The name only appears on the first sentence; the rest of the turn is one voice.
        name, voice, reply = None, DEFAULT_VOICE, llm.Reply("", None)
        try:
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "done":
                    reply = chunk
                    continue
                if name is None:
                    found, chunk = split_speaker(chunk)
                    if found:
                        name, voice = found, PANEL[found][0]
                    if not chunk:
                        continue
                await io.send(type="sentence", text=chunk, speaker=name)
                await io.say(chunk, voice=voice)
        except Exception as exc:
            await io.send(type="error", text=await llm.explain(endpoint, exc))
            history.pop()
            continue

        if reply.text:
            history.append({"role": "assistant", "content": reply.text})
            store.record(f"panel:{name or '?'}", reply.text, reply_ms=reply.ms)
        await io.send(type="turn_done", latency_ms=reply.ms)
        await io.drain()
