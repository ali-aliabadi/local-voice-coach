"""
Local English conversation partner: push-to-talk STT -> LLM -> streaming TTS.
All config lives in the constants below.
"""

import asyncio
import re
import sys
import termios
import time
import tty

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro
from openai import AsyncOpenAI

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

# ---- LLM (LM Studio / any OpenAI-compatible local server) ----
LLM_BASE_URL = "http://localhost:1234/v1"
LLM_API_KEY = "lm-studio"
# Must match the identifier LM Studio exposes. Check: curl localhost:1234/v1/models
LLM_MODEL = "qwen3-4b-instruct-2507-mlx"
LLM_TEMPERATURE = 0.7
LLM_MAX_TOKENS = 120            # hard cap; prompt already asks for brevity
HISTORY_TURNS = 8               # user+assistant pairs kept in context
SYSTEM_PROMPT = (
    "You are a friendly conversational English practice partner. "
    "Keep every reply to 1 or 2 short sentences so the conversation stays fast "
    "and fluid. Ask a natural follow-up question when it makes sense. "
    "Never correct the user's grammar or mention their mistakes."
)

# ---- STT ----
WHISPER_MODEL = "small.en"      # drop to "base.en" if transcription feels slow
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
BEAM_SIZE = 1                   # greedy; raise to 5 if accuracy suffers
VAD_FILTER = False

# ---- Audio ----
SAMPLE_RATE = 16000             # Whisper expects 16kHz
MIN_RECORD_SECONDS = 0.3        # ignore accidental double-taps

# ---- TTS ----
TTS_MODEL_PATH = "kokoro-v1.0.onnx"
TTS_VOICES_PATH = "voices-v1.0.bin"
TTS_VOICE = "am_puck"
TTS_SPEED = 1.0

# ---- Chunking / logging ----
MAX_CHARS_BEFORE_FLUSH = 160    # speak long run-on output without waiting
LOG_PATH = "english_practice_log.md"

TERMINATORS = (".", "!", "?", "…")
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class QuitRequested(Exception):
    pass


# --------------------------------------------------------------------------
# TERMINAL INPUT
# --------------------------------------------------------------------------

def get_key() -> str:
    """Read one keypress without waiting for Enter. Uses cbreak so Ctrl-C still works."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)   # NOT setraw: raw mode disables Ctrl-C
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# --------------------------------------------------------------------------
# RECORDING
# --------------------------------------------------------------------------

async def record_audio_segment() -> np.ndarray | None:
    loop = asyncio.get_running_loop()
    audio_buffer: list[np.ndarray] = []

    def callback(indata, frames, time_info, status):
        audio_buffer.append(indata.copy())

    print("\n👉 [Press any key to start speaking, or 'q' to quit]")
    key = await loop.run_in_executor(None, get_key)
    if key.lower() == "q":
        raise QuitRequested

    print("🎙️  Recording... press any key to stop.")
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, callback=callback, dtype="float32"
    )
    with stream:
        await loop.run_in_executor(None, get_key)

    if not audio_buffer:
        return None

    audio = np.concatenate(audio_buffer, axis=0).flatten()
    if len(audio) < MIN_RECORD_SECONDS * SAMPLE_RATE:
        return None
    return audio


# --------------------------------------------------------------------------
# TTS PLAYBACK WORKER
# --------------------------------------------------------------------------

async def speaker_worker(queue: asyncio.Queue, tts: Kokoro) -> None:
    """Consumes sentences and plays them, so the LLM can keep generating meanwhile."""
    loop = asyncio.get_running_loop()
    while True:
        sentence = await queue.get()
        if sentence is None:
            queue.task_done()
            return
        try:
            samples, sr = await loop.run_in_executor(
                None,
                lambda s=sentence: tts.create(s, voice=TTS_VOICE, speed=TTS_SPEED),
            )
            await loop.run_in_executor(None, lambda: (sd.play(samples, sr), sd.wait()))
        except Exception as exc:
            print(f"⚠️  TTS error: {exc}")
        finally:
            queue.task_done()


# --------------------------------------------------------------------------
# SENTENCE CHUNKING
# --------------------------------------------------------------------------

def ready_to_speak(buffer: str) -> bool:
    # ponytail: naive sentence heuristic; swap in a real segmenter if it mis-splits
    text = buffer.strip()
    if len(text) < 3:
        return False
    if "\n" in buffer or len(text) >= MAX_CHARS_BEFORE_FLUSH:
        return True
    if not text.endswith(TERMINATORS):
        return False
    if text.endswith(".") and text[-2].isdigit():   # "3.5"
        return False
    if re.search(r"\b(Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e)\.$", text):
        return False
    return True


# --------------------------------------------------------------------------
# LOGGING
# --------------------------------------------------------------------------

def log_turn(role: str, text: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(f"- **{role}** ({stamp}): {text}\n")


# --------------------------------------------------------------------------
# MAIN PIPELINE
# --------------------------------------------------------------------------

async def pipeline() -> None:
    loop = asyncio.get_running_loop()

    print("⏳ Loading Whisper (STT)...")
    stt = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
    print("⏳ Loading Kokoro (TTS)...")
    tts = Kokoro(TTS_MODEL_PATH, TTS_VOICES_PATH)
    llm = AsyncOpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    print("✅ Models loaded.")

    speech_queue: asyncio.Queue = asyncio.Queue()
    worker = asyncio.create_task(speaker_worker(speech_queue, tts))
    history: list[dict] = []

    try:
        while True:
            audio = await record_audio_segment()
            if audio is None:
                print("⚠️  Nothing recorded — hold the recording a bit longer.")
                continue

            print("🛑 Transcribing...")
            t0 = time.perf_counter()
            segments = await loop.run_in_executor(
                None,
                lambda: list(
                    stt.transcribe(
                        audio,
                        beam_size=BEAM_SIZE,
                        vad_filter=VAD_FILTER,
                        language="en",
                        condition_on_previous_text=False,
                    )[0]
                ),
            )
            user_text = " ".join(s.text for s in segments).strip()
            stt_ms = (time.perf_counter() - t0) * 1000

            if not user_text:
                print("⚠️  Didn't catch that. Try speaking closer to the mic.")
                continue

            print(f'\nYou ({stt_ms:.0f}ms): "{user_text}"')
            log_turn("User", user_text)

            history.append({"role": "user", "content": user_text})
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            messages += history[-HISTORY_TURNS * 2:]

            print("🤖 Thinking...", end="\r", flush=True)
            t0 = time.perf_counter()
            first_token_ms = None

            stream = await llm.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=LLM_TEMPERATURE,
                max_tokens=LLM_MAX_TOKENS,
                stream=True,
            )

            buffer, full_reply = "", ""
            async for chunk in stream:
                if not chunk.choices:
                    continue
                token = chunk.choices[0].delta.content or ""
                if not token:
                    continue
                if first_token_ms is None:
                    first_token_ms = (time.perf_counter() - t0) * 1000
                buffer += token
                full_reply += token

                if ready_to_speak(buffer):
                    sentence = THINK_RE.sub("", buffer).strip()
                    if sentence:
                        print(f"AI: {sentence}")
                        await speech_queue.put(sentence)
                    buffer = ""

            # Flush whatever is left (replies without terminal punctuation)
            tail = THINK_RE.sub("", buffer).strip()
            if tail:
                print(f"AI: {tail}")
                await speech_queue.put(tail)

            clean_reply = THINK_RE.sub("", full_reply).strip()
            if clean_reply:
                history.append({"role": "assistant", "content": clean_reply})
                log_turn("AI", clean_reply)

            if first_token_ms is not None:
                print(f"   ⏱  first token: {first_token_ms:.0f}ms")

            # Don't record over the AI's own voice
            await speech_queue.join()

    except QuitRequested:
        print("\nExiting. Keep practicing!")
    finally:
        sd.stop()
        await speech_queue.put(None)
        await worker


if __name__ == "__main__":
    try:
        asyncio.run(pipeline())
    except KeyboardInterrupt:
        sd.stop()
        print("\nSession ended.")
