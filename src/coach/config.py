"""Every tunable in the project. Contributors: start here."""

import contextlib
import os
import pathlib


def load_env(path: str = ".env") -> None:
    """Minimal .env reader. Real env vars win, so `GEMINI_API_KEY=... python main.py` overrides."""
    with contextlib.suppress(FileNotFoundError):
        for raw in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env()

# ---- LLM: Gemini through its OpenAI-compatible endpoint ----
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Temperature, token budgets, history length, voice, speed, Whisper model and the pause
# threshold are user-facing, so they live in settings.SPEC with their defaults.

REQUEST_TIMEOUT = 45.0  # a cold call measured 16s and one hung at 51s, so this catches hangs
# without aborting slow-but-working requests; the SDK retries twice on its own
# In conversation, silence is the failure. A reply that has not started after this long is
# abandoned and asked again once - a cold call measured 16s, and one stream sat silent for
# the full 45s and then gave up, leaving the user to repeat themselves.
FIRST_WORD_SECONDS = 20.0

# ---- STT (local) ----
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
BEAM_SIZE = 1  # greedy; raise to 5 if accuracy suffers
# Whisper is trained to tidy speech up and silently drops "um"/"uh". This biases it to
# keep them. ponytail: crude; CrisperWhisper does verbatim properly if exact counts matter.
DISFLUENCY_HINT = "Um, uh, hmm, er, mmm, so, well, you know, I mean."
# Below this confidence a word is marked "the transcriber was unsure". A proxy for an
# unclear word - or a mishearing - never a pronunciation score. Calibration knob.
UNCLEAR_BELOW = 0.5

# ---- Audio ----
SAMPLE_RATE = 16000  # Whisper expects 16kHz
MIN_RECORD_SECONDS = 0.3  # ignore accidental double-taps


# ---- TTS (local) ----
def _weights(name: str, override: str) -> str:
    """Find a model file. `make models` puts them in models/, but the repo root has
    always worked too, so both are accepted rather than breaking an existing checkout."""
    chosen = os.environ.get(override)
    if chosen:
        return chosen
    for candidate in (pathlib.Path("models") / name, pathlib.Path(name)):
        if candidate.exists():
            return str(candidate)
    return str(pathlib.Path("models") / name)  # where we will tell you to put it


TTS_MODEL_PATH = _weights("kokoro-v1.0.onnx", "KOKORO_MODEL")
TTS_VOICES_PATH = _weights("voices-v1.0.bin", "KOKORO_VOICES")
# The study sheet's typeface (Inter, OFL). Pillow's own font has no dashes, arrows or
# accented letters; without this file the sheet still renders, in plain ASCII.
REPORT_FONT = _weights("Inter.ttf", "REPORT_FONT")
# Only fires when a sentence never ends. Sentence boundaries are found properly now, so
# this is a backstop against pathological output - not a routine cut. Low values chop
# ordinary long sentences in half, which is exactly the bug it used to cause.
MAX_CHARS_BEFORE_FLUSH = 280

# Everything the user accumulates lives here. Set DATA_DIR to keep it outside the working
# directory - the container mounts a volume at /data so a rebuild does not wipe it.
DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", "."))
DB_PATH = str(DATA_DIR / "practice.db")
RECORDINGS = DATA_DIR / "recordings"
