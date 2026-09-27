"""Speech to text, plus the fluency numbers derived from word timings."""

import asyncio
import re
import time

from faster_whisper import WhisperModel

from . import config

# Only unambiguous disfluencies. "like" and "so" are real words too often to count them
# without drowning the score in false positives.
FILLER_RE = re.compile(r"(u+m+|u+h+|e+r+|a+h+|h+m+|m+h*)", re.I)


def fluency(words) -> dict | None:
    """Per-answer fluency stats from word timestamps. Pure arithmetic - no model, no network."""
    if not words:
        return None
    speaking = words[-1].end - words[0].start
    gaps = [b.start - a.end for a, b in zip(words, words[1:], strict=False)]
    return {
        "words": len(words),
        "wpm": round(len(words) / speaking * 60) if speaking > 0 else 0,
        "fillers": sum(bool(FILLER_RE.fullmatch(w.word.strip(" ,.!?-"))) for w in words),
        "pauses": sum(g >= config.PAUSE_SECONDS for g in gaps),
        "longest_pause": round(max(max(gaps, default=0.0), 0.0), 1),
        "lead_in": round(words[0].start, 1),
    }


def format_metrics(m: dict) -> str:
    return (
        f"{m['wpm']} wpm · {m['fillers']} fillers · {m['pauses']} pauses "
        f"(longest {m['longest_pause']}s) · started after {m['lead_in']}s"
    )


class Transcriber:
    """Holds the loaded Whisper model; transcribing runs off the event loop."""

    def __init__(self):
        self.model = WhisperModel(
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )

    async def transcribe(self, audio) -> tuple[str, dict | None, float]:
        """Returns (text, fluency metrics, elapsed ms)."""
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        segments = await loop.run_in_executor(
            None,
            lambda: list(
                self.model.transcribe(
                    audio,
                    beam_size=config.BEAM_SIZE,
                    language="en",
                    condition_on_previous_text=False,
                    word_timestamps=True,  # load-bearing: the metrics need these
                    initial_prompt=config.DISFLUENCY_HINT,
                )[0]
            ),
        )
        words = [w for s in segments for w in (s.words or [])]
        text = " ".join(s.text for s in segments).strip()
        return text, fluency(words), (time.perf_counter() - started) * 1000
