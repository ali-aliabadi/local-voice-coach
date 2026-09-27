"""Kokoro speech, encoded as WAV bytes for the browser to play.

Nothing here touches an audio device. The server only ever produces bytes; the browser
decides when they are heard.
"""

import asyncio
import io
import wave

import numpy as np
from kokoro_onnx import Kokoro

from . import config, settings


def encode_wav(samples: np.ndarray, rate: int) -> bytes:
    """float32 in [-1, 1] -> 16-bit mono WAV. Also used for the user's own recordings."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()


class Voice:
    """The loaded Kokoro model. Synthesis runs off the event loop."""

    def __init__(self) -> None:
        self.kokoro = Kokoro(config.TTS_MODEL_PATH, config.TTS_VOICES_PATH)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.kokoro.get_voices()))

    async def wav(self, text: str, voice: str | None = None) -> bytes:
        loop = asyncio.get_running_loop()
        chosen = voice or settings.get("tts_voice")
        speed = settings.get("tts_speed")
        samples, rate = await loop.run_in_executor(
            None, lambda: self.kokoro.create(text, voice=chosen, speed=speed)
        )
        return encode_wav(samples, rate)
