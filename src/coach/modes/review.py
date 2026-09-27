"""review — one hard question at a time, then a written technical critique.

Deliberately slow. Latency does not matter here, so this uses the thinking model and
asks it for the kind of depth a real interviewer would actually probe. The question is
spoken; the critique is printed, because nobody wants to listen to six paragraphs.
"""

from .. import config, llm, store
from ..audio import QuitRequested, record_answer
from ..stt import format_metrics

HELP = "one hard question, then a written technical critique"
ENDPOINT = "deep"

ASK_PROMPT = (
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
    "Cover, with a short heading each:\n"
    "1. Verdict — one line, and a score out of 5.\n"
    "2. What was actually right, naming the specific claims that held up.\n"
    "3. What was wrong, missing, or too vague - quote their words where useful.\n"
    "4. What a real interviewer would ask next to probe the weak spot.\n"
    "5. A stronger version of the answer, in 3-4 sentences they could actually say.\n\n"
    "Judge the engineering, not the English. Do not correct grammar or vocabulary. "
    "The delivery numbers are given only so you can comment on pacing and hesitation in "
    "the verdict line if something stands out; ignore them otherwise."
)


async def run(endpoint, transcriber, speaker) -> list[dict]:
    history: list[dict] = []
    scores: list[dict] = []

    print("\n🔬 Review mode: slower, deeper. Replies are printed, not spoken.")

    while True:
        # --- ask ---
        messages = [{"role": "system", "content": ASK_PROMPT}]
        messages += history[-config.HISTORY_TURNS * 2 :]
        print("\n🤔 Composing a question...", end="\r", flush=True)
        try:
            asked = llm.Reply("", None)
            async for kind, chunk in llm.stream_sentences(endpoint, messages):
                if kind == "sentence":
                    print(f"Interviewer: {chunk}")
                    await speaker.say(chunk)
                else:
                    asked = chunk
        except Exception as exc:
            print(f"\n⚠️  LLM error: {exc}")
            await llm.describe_error(endpoint, exc)
            return scores
        await speaker.drain()
        question = asked.text
        store.record("interviewer", question, reply_ms=asked.ms)

        # --- answer ---
        try:
            audio = await record_answer("[Any key to answer, 'q' to finish]")
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

        # --- critique ---
        delivery = format_metrics(metrics) if metrics else "not measured"
        print("\n🔬 Reviewing (this one takes a few seconds)...")
        try:
            critique = await llm.complete(
                endpoint,
                [
                    {"role": "system", "content": CRITIQUE_PROMPT},
                    {
                        "role": "user",
                        "content": f"Question asked:\n{question}\n\n"
                        f"Candidate's answer:\n{text}\n\n"
                        f"Delivery numbers: {delivery}",
                    },
                ],
            )
        except Exception as exc:
            print(f"⚠️  LLM error: {exc}")
            continue

        print(f"\n{critique.text}\n   ⏱  {critique.ms / 1000:.1f}s\n")
        store.record("review", critique.text, reply_ms=critique.ms)
        history.append({"role": "user", "content": f"Q: {question}\nA: {text}"})
        history.append({"role": "assistant", "content": critique.text[:400]})
