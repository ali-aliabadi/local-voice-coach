"""talk — the default. One interviewer, fast replies, fluency scored per answer.

Optimised for reps: you want the conversation to feel live, so this uses the fast
model and never blocks on anything it doesn't have to.
"""

from .. import config, llm, store
from ..audio import QuitRequested, record_answer
from ..stt import format_metrics

HELP = "fast conversation, fluency scored per answer (default)"
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


async def run(endpoint, transcriber, speaker) -> list[dict]:
    history: list[dict] = []
    scores: list[dict] = []

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
        try:
            reply = llm.Reply("", None)
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "sentence":
                    print(f"Interviewer: {chunk}")
                    await speaker.say(chunk)
                else:
                    reply = chunk
        except Exception as exc:
            print(f"\n⚠️  LLM error: {exc}")
            await llm.describe_error(endpoint, exc)
            history.pop()  # don't poison context with an unanswered turn
            continue

        if reply.text:
            history.append({"role": "assistant", "content": reply.text})
            store.record("interviewer", reply.text, reply_ms=reply.ms)
            print(f"   ⏱  first token: {reply.ms:.0f}ms")

        await speaker.drain()  # don't record over the interviewer's own voice
