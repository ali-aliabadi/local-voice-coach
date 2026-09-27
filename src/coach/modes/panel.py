"""panel — two or more interviewers, each with their own voice.

Closer to a real onsite: someone warm, someone digging into the technical detail, and
someone pushing back. Kokoro ships 54 voices, so the panel costs nothing extra to run.
"""

import re

from .. import config, llm, store
from ..audio import QuitRequested, record_answer
from ..stt import format_metrics

HELP = "several interviewers, one Kokoro voice each"
ENDPOINT = "fast"

# name -> (kokoro voice, what they care about). Add a row and they join the panel.
PANEL = {
    "MAYA": ("af_heart", "the hiring manager: warm, asks behavioural and motivation questions"),
    "DEREK": ("bm_george", "a staff engineer: digs into system design and technical trade-offs"),
    "PRIYA": (
        "af_nicole",
        "the bar raiser: politely pushes back, asks about edge cases and failure modes",
    ),
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


async def run(endpoint, transcriber, speaker) -> list[dict]:
    history: list[dict] = []
    scores: list[dict] = []

    print("\n🎤 Panel: " + ", ".join(PANEL))

    while True:
        try:
            audio = await record_answer()
        except QuitRequested:
            return scores

        if audio is None:
            print("⚠️  Nothing recorded — hold it a bit longer.")
            continue

        print("🛑 Transcribing...")
        text, metrics, stt_ms = await transcriber.transcribe(audio)
        if not text:
            print("⚠️  Didn't catch that. Try speaking closer to the mic.")
            continue

        print(f'\nYou ({stt_ms:.0f}ms): "{text}"')
        if metrics:
            scores.append(metrics)
            print(f"   📊 {format_metrics(metrics)}")
        store.record("you", text, metrics, stt_ms=stt_ms)

        history.append({"role": "user", "content": text})
        messages = [{"role": "system", "content": PROMPT}]
        messages += history[-config.HISTORY_TURNS * 2 :]

        print("🤖 Thinking...", end="\r", flush=True)
        # The name only appears on the first sentence; the rest of the turn is the same voice.
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
                print(f"{name or 'Panel'}: {chunk}")
                await speaker.say(chunk, voice=voice)
        except Exception as exc:
            print(f"\n⚠️  LLM error: {exc}")
            await llm.describe_error(endpoint, exc)
            history.pop()
            continue

        if reply.text:
            history.append({"role": "assistant", "content": reply.text})
            store.record(f"panel:{name or '?'}", reply.text, reply_ms=reply.ms)
            print(f"   ⏱  first token: {reply.ms:.0f}ms")

        await speaker.drain()
