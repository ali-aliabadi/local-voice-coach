"""Every tunable in the project. Contributors: start here."""

import os


def load_env(path: str = ".env") -> None:
    """Minimal .env reader. Real env vars win, so `GEMINI_API_KEY=... python main.py` overrides."""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except FileNotFoundError:
        pass


load_env()

# ---- LLM: Gemini through its OpenAI-compatible endpoint ----
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Which backend plays the interviewer now lives in backends.py, chosen at startup.
# Set these in .env to skip the prompts entirely once you have settled on a favourite:
#     MODE=talk
#     BACKEND=flash-lite
DEFAULT_MODE = os.environ.get("MODE", "")
DEFAULT_BACKEND = os.environ.get("BACKEND", "")

TEMPERATURE = 0.7
REPLY_MAX_TOKENS = 200  # spoken replies measure ~20-40 tokens; headroom for thinking
REVIEW_MAX_TOKENS = 2500  # written critique; local reasoners spend a lot on thinking
HISTORY_TURNS = 8  # user+assistant pairs kept in context; drives token cost
REQUEST_TIMEOUT = 20.0  # one test request hung 51s; SDK retries twice on its own

# ---- STT (local) ----
WHISPER_MODEL = "small.en"  # drop to "base.en" if transcription feels slow
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"
BEAM_SIZE = 1  # greedy; raise to 5 if accuracy suffers
# Whisper is trained to tidy speech up and silently drops "um"/"uh". This biases it to
# keep them. ponytail: crude; CrisperWhisper does verbatim properly if exact counts matter.
DISFLUENCY_HINT = "Um, uh, hmm, er, mmm, so, well, you know, I mean."

# ---- Audio ----
SAMPLE_RATE = 16000  # Whisper expects 16kHz
MIN_RECORD_SECONDS = 0.3  # ignore accidental double-taps

# ---- TTS (local) ----
TTS_MODEL_PATH = "kokoro-v1.0.onnx"
TTS_VOICES_PATH = "voices-v1.0.bin"
TTS_VOICE = "am_puck"  # 54 voices ship in voices-v1.0.bin; see panel.py
TTS_SPEED = 1.0
MAX_CHARS_BEFORE_FLUSH = 160  # speak long run-on output without waiting for a full stop

# ---- Fluency scoring ----
PAUSE_SECONDS = 0.6  # calibration knob: gap a listener notices as hesitation

DB_PATH = "practice.db"
