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

# Words per minute of each accent voice at speed 1.0, measured by voicing every partner
# reply of two real sessions (3,862 words). They differ by a quarter - am_michael 185,
# am_puck 235 - so a session's pace used to depend on which accent it drew.
PACE = {
    "af_heart": 200, "bm_george": 194, "am_michael": 185, "bf_emma": 217,
    "af_bella": 200, "bm_fable": 230, "am_puck": 235, "bf_isabella": 215,
}  # fmt: skip
# The pace every accent is brought to: a fluent native speaker's, never the learner's.
# It is am_puck's natural pace, the quickest voice that still sounds unhurried. Speech
# speed in Settings is the one knob for slowing down.
FLUENT = PACE["am_puck"]


def pace(voice: str) -> float:
    """The speed at which `voice` talks at a fluent speaker's pace, whichever voice is
    chosen in Settings. A voice never measured is left as it is.

    Kokoro's speed is not exactly proportional to pace - between 0.8 and 1.4 it landed
    within 6% of the ratio asked for, in steps rather than a curve - so a plain ratio is
    as close as a fitted one, and far closer than the quarter the voices used to differ by.
    """
    return FLUENT / PACE[voice] if voice in PACE else 1.0


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

    async def wav(self, text: str, voice: str | None = None, slower: bool = False) -> bytes:
        """Every accent at a fluent speaker's pace, times the Speech speed setting.
        `slower` is for "say that again, slower": a fifth off that."""
        loop = asyncio.get_running_loop()
        chosen = voice or settings.get("tts_voice")
        speed = settings.get("tts_speed") * pace(chosen) * (0.8 if slower else 1.0)
        samples, rate = await loop.run_in_executor(
            None, lambda: self.kokoro.create(text, voice=chosen, speed=speed)
        )
        return encode_wav(samples, rate)
