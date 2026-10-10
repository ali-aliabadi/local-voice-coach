"""Scoring an answer: fillers, pauses, pace and lead-in are arithmetic on word timestamps."""

import json
import pathlib
import wave
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from coach import stt
from coach.stt import filler_pattern, fluency, word_rows

SPOKEN = pathlib.Path(__file__).with_name("i-think-so.wav")


@dataclass
class W:
    """Stands in for faster-whisper's Word."""

    start: Any  # a float, or numpy's, as faster-whisper hands them back
    end: Any
    word: str
    probability: Any = 0.95


def say(*triples):
    return [W(start, end, word) for word, start, end in triples]


def scored(*triples) -> dict:
    metrics = fluency(say(*triples))
    assert metrics is not None
    return metrics


@pytest.mark.parametrize("drawn_out", ["um", "ummm", "uhhh", "mmmm", "hmm", "Um"])
def test_a_filler_counts_however_long_it_is_drawn_out(drawn_out):
    assert filler_pattern("um uh er ah hmm mm").fullmatch(drawn_out)


@pytest.mark.parametrize("real_word", ["umbrella", "humming", "Redis", "another"])
def test_a_real_word_is_never_a_filler(real_word):
    assert not filler_pattern("um uh er ah hmm mm").fullmatch(real_word)


def test_an_empty_filler_list_matches_nothing_not_everything():
    assert not filler_pattern("").fullmatch("um")


def test_nothing_said_has_no_score():
    assert fluency([]) is None


def test_one_word_has_no_pause():
    solo = scored(("yes", 0.5, 0.9))
    assert solo["words"] == 1
    assert solo["longest_pause"] == 0.0


def test_a_smooth_answer():
    smooth = scored(("I", 0, 0.5), ("built", 0.5, 1), ("a", 1, 1.5), ("service", 1.5, 2))
    assert smooth["wpm"] == 120
    assert smooth["pauses"] == 0
    assert smooth["fillers"] == 0
    assert smooth["lead_in"] == 0.0


def test_fillers_are_counted():
    hesitant = scored(("Um,", 0, 0.4), ("mmmm", 0.4, 1), ("uh", 1, 1.4), ("Redis", 1.4, 2))
    assert hesitant["fillers"] == 3


def test_a_gap_over_the_threshold_is_a_pause():
    gappy = scored(("So", 0, 0.3), ("I", 2, 2.2), ("used", 2.3, 2.6), ("Postgres", 2.7, 3.2))
    assert gappy["pauses"] == 1
    assert gappy["longest_pause"] == 1.7


def test_lead_in_is_the_silence_before_the_first_word():
    assert scored(("Well", 3.4, 3.8), ("yes", 3.8, 4.1))["lead_in"] == 3.4


@pytest.mark.parametrize("silence", [0.3, 0.8, 1.5])
def test_the_first_word_starts_where_the_speech_does(silence):
    """Whisper stretched the first word back over the silence: 0.8s before "I" read as
    " I" from 0.0 to 0.9, so 'before you spoke' said 0."""
    with wave.open(str(SPOKEN), "rb") as clip:  # "I think so.", by Kokoro, at 16kHz
        voice = np.frombuffer(clip.readframes(clip.getnframes()), "<i2") / 32768
    audio = np.concatenate([np.zeros(int(silence * 16000)), voice]).astype(np.float32)
    words = stt.to_onset(say(("I", 0.0, silence + 0.2), ("think", silence + 0.2, 1.0)), audio)
    assert abs(words[0].start - silence) < 0.1
    assert words[1].start == silence + 0.2  # only the first word was wrong


def test_whisper_stands_where_no_speech_is_found():
    words = say(("Yes", 0.4, 0.9))
    assert stt.to_onset(words, np.zeros(16000, np.float32)) == words


def test_numpy_scalars_leave_as_plain_python():
    """faster-whisper hands back numpy scalars, which JSON and sqlite3 both reject."""
    words = [
        W(np.float32(0.0), np.float32(0.5), "I"),
        W(np.float32(1.4), np.float32(2.0), "um", np.float32(0.4)),
    ]
    metrics = fluency(words)
    assert metrics is not None
    json.dumps(metrics)
    json.dumps(word_rows(words))
    assert all(type(v) in (int, float) for v in metrics.values())


def test_word_rows_mark_fillers_and_the_pause_before_each_word():
    rows = word_rows(say(("So", 0.0, 0.3), ("um", 2.0, 2.4), ("Redis", 2.5, 3.0)))
    assert [r["word"] for r in rows] == ["So", "um", "Redis"]
    assert rows[1]["filler"]
    assert not rows[2]["filler"]
    assert rows[1]["pause"] == 1.7  # beats the threshold
    assert rows[2]["pause"] == 0.0  # 0.1s is below it
    assert rows[0]["pause"] == 0.0  # nothing precedes the first word


def test_low_confidence_is_marked_unclear_never_scored_as_pronunciation():
    rows = word_rows([W(0.0, 0.4, "middling", probability=0.31), W(0.5, 0.9, "mind")])
    assert rows[0]["unclear"]
    assert not rows[1]["unclear"]


def test_fetch_downloads_the_repo_faster_whisper_would(monkeypatch):
    monkeypatch.setattr(stt, "snapshot_download", lambda repo, **_: repo)
    assert stt.fetch("small.en") == "Systran/faster-whisper-small.en"
    assert stt.fetch("distil-small.en") == "Systran/faster-distil-whisper-small.en"
