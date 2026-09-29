"""The loaded Whisper and Kokoro models.

Their own module so the API routes and the websocket handler can both reach them without
importing each other.
"""

from .. import stt, tts

_loaded: dict = {}


def load() -> None:
    print("  loading Whisper...")
    _loaded["stt"] = stt.Transcriber()
    print("  loading Kokoro...")
    _loaded["voice"] = tts.Voice()


def transcriber() -> "stt.Transcriber":
    return _loaded["stt"]


def voice() -> "tts.Voice":
    return _loaded["voice"]


def voice_names() -> tuple[str, ...]:
    return _loaded["voice"].names() if "voice" in _loaded else ()
