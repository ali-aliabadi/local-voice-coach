"""Speech to text, plus the fluency numbers derived from word timings."""

import asyncio
import itertools
import re
import time
from collections.abc import Sequence
from typing import Any

import numpy as np
from faster_whisper import WhisperModel

from . import config, settings


def filler_pattern(words: str) -> re.Pattern:
    """'um uh mm' -> a regex that also catches 'ummm' and 'mmmm'.

    Each run of a repeated letter becomes one `x+`, so a word is matched however long the
    speaker drew it out. Only unambiguous disfluencies belong here: 'like' and 'so' are
    real words too often to count without drowning the score in false positives.
    """
    parts = []
    for word in words.split():
        squeezed = re.sub(r"(.)\1*", r"\1", word.lower())
        parts.append("".join(f"{re.escape(c)}+" for c in squeezed))
    return re.compile("|".join(parts) if parts else r"(?!)", re.I)


def fluency(words: Sequence[Any]) -> dict | None:
    """Per-answer stats from word timestamps. Pure arithmetic - no model, no network."""
    if not words:
        return None
    pause_seconds = settings.get("pause_seconds")
    filler_re = filler_pattern(settings.get("filler_words"))
    speaking = float(words[-1].end) - float(words[0].start)
    gaps = [float(b.start) - float(a.end) for a, b in itertools.pairwise(words)]
    # int()/float() are load-bearing: faster-whisper returns numpy scalars, which are
    # neither JSON serialisable nor accepted by sqlite3.
    return {
        "words": len(words),
        "wpm": round(len(words) / speaking * 60) if speaking > 0 else 0,
        "fillers": int(sum(bool(filler_re.fullmatch(w.word.strip(" ,.!?-"))) for w in words)),
        "pauses": int(sum(g >= pause_seconds for g in gaps)),
        "longest_pause": round(max(max(gaps, default=0.0), 0.0), 1),
        "lead_in": round(float(words[0].start), 1),
    }


def word_rows(words: Sequence[Any]) -> list[dict]:
    """Per-word data for the browser: it draws the highlighted transcript and the timeline."""
    filler_re = filler_pattern(settings.get("filler_words"))
    pause_seconds = settings.get("pause_seconds")
    rows = []
    previous_end = None
    for word in words:
        gap = 0.0 if previous_end is None else float(word.start) - previous_end
        rows.append(
            {
                "word": word.word.strip(),
                "start": round(float(word.start), 2),
                "end": round(float(word.end), 2),
                "filler": bool(filler_re.fullmatch(word.word.strip(" ,.!?-"))),
                "pause": round(gap, 2) if gap >= pause_seconds else 0.0,
                "unclear": float(getattr(word, "probability", 1.0)) < config.UNCLEAR_BELOW,
            }
        )
        previous_end = float(word.end)
    return rows


class Transcriber:
    """Holds the loaded Whisper model; transcribing runs off the event loop."""

    def __init__(self) -> None:
        self.model = WhisperModel(
            settings.get("whisper_model"),
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE,
        )

    async def transcribe(self, audio: np.ndarray) -> tuple[str, dict | None, list[dict], float]:
        """Returns (text, metrics, per-word rows, elapsed ms)."""
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
        return text, fluency(words), word_rows(words), (time.perf_counter() - started) * 1000
