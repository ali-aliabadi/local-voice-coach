"""Microphone in, speaker out. Nothing here touches the network."""

import asyncio
import sys
import termios
import tty

import numpy as np
import sounddevice as sd

from . import config


class QuitRequested(Exception):
    """Raised from the recorder so any mode's loop unwinds the same way."""


def get_key() -> str:
    """Read one keypress without waiting for Enter. cbreak, not raw, so Ctrl-C still works."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


async def record_answer(prompt: str = "[Any key to answer, 'q' to finish]") -> np.ndarray | None:
    """Push to talk. Returns None if nothing usable was captured."""
    loop = asyncio.get_running_loop()
    chunks: list[np.ndarray] = []

    def callback(indata, _frames, _time, _status):  # signature fixed by sounddevice
        chunks.append(indata.copy())

    print(f"\n👉 {prompt}")
    if (await loop.run_in_executor(None, get_key)).lower() == "q":
        raise QuitRequested

    print("🎙️  Listening... press any key when you're done.")
    stream = sd.InputStream(
        samplerate=config.SAMPLE_RATE, channels=1, callback=callback, dtype="float32"
    )
    with stream:
        await loop.run_in_executor(None, get_key)

    if not chunks:
        return None
    audio = np.concatenate(chunks, axis=0).flatten()
    if len(audio) < config.MIN_RECORD_SECONDS * config.SAMPLE_RATE:
        return None
    return audio


class Speaker:
    """Plays sentences on a background task so the LLM can keep generating meanwhile."""

    def __init__(self, tts):
        self.tts = tts
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task = asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                return
            text, voice = item
            try:
                # Bind loop values as defaults: these lambdas must not see a later turn's.
                samples, rate = await loop.run_in_executor(
                    None,
                    lambda t=text, v=voice: self.tts.create(t, voice=v, speed=config.TTS_SPEED),
                )
                await loop.run_in_executor(
                    None, lambda s=samples, r=rate: (sd.play(s, r), sd.wait())
                )
            except Exception as exc:
                print(f"⚠️  TTS error: {exc}")
            finally:
                self.queue.task_done()

    async def say(self, text: str, voice: str = config.TTS_VOICE) -> None:
        await self.queue.put((text, voice))

    async def drain(self) -> None:
        """Wait for everything queued to finish playing, so we don't record over it."""
        await self.queue.join()

    async def close(self) -> None:
        sd.stop()
        await self.queue.put(None)
        await self.task
