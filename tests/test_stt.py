"""Scoring an answer: fillers, pauses, pace and lead-in are arithmetic on word timestamps."""

import json
from dataclasses import dataclass

import numpy as np
import pytest

from coach.stt import filler_pattern, fluency, word_rows


@dataclass
class W:
    """Stands in for faster-whisper's Word."""

    start: float
    end: float
    word: str
    probability: float = 0.95


def say(*triples):
    return [W(start, end, word) for word, start, end in triples]


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
    solo = fluency(say(("yes", 0.5, 0.9)))
    assert solo["words"] == 1 and solo["longest_pause"] == 0.0


def test_a_smooth_answer():
    smooth = fluency(say(("I", 0, 0.5), ("built", 0.5, 1), ("a", 1, 1.5), ("service", 1.5, 2)))
    assert smooth["wpm"] == 120
    assert smooth["pauses"] == 0 and smooth["fillers"] == 0 and smooth["lead_in"] == 0.0


def test_fillers_are_counted():
    hesitant = fluency(say(("Um,", 0, 0.4), ("mmmm", 0.4, 1), ("uh", 1, 1.4), ("Redis", 1.4, 2)))
    assert hesitant["fillers"] == 3


def test_a_gap_over_the_threshold_is_a_pause():
    gappy = fluency(say(("So", 0, 0.3), ("I", 2, 2.2), ("used", 2.3, 2.6), ("Postgres", 2.7, 3.2)))
    assert gappy["pauses"] == 1 and gappy["longest_pause"] == 1.7


def test_lead_in_is_the_silence_before_the_first_word():
    assert fluency(say(("Well", 3.4, 3.8), ("yes", 3.8, 4.1)))["lead_in"] == 3.4


def test_numpy_scalars_leave_as_plain_python():
    """faster-whisper hands back numpy scalars, which JSON and sqlite3 both reject."""
    words = [
        W(np.float32(0.0), np.float32(0.5), "I"),
        W(np.float32(1.4), np.float32(2.0), "um", np.float32(0.4)),
    ]
    metrics = fluency(words)
    json.dumps(metrics)
    json.dumps(word_rows(words))
    assert all(type(v) in (int, float) for v in metrics.values())


def test_word_rows_mark_fillers_and_the_pause_before_each_word():
    rows = word_rows(say(("So", 0.0, 0.3), ("um", 2.0, 2.4), ("Redis", 2.5, 3.0)))
    assert [r["word"] for r in rows] == ["So", "um", "Redis"]
    assert rows[1]["filler"] and not rows[2]["filler"]
    assert rows[1]["pause"] == 1.7  # beats the threshold
    assert rows[2]["pause"] == 0.0  # 0.1s is below it
    assert rows[0]["pause"] == 0.0  # nothing precedes the first word


def test_low_confidence_is_marked_unclear_never_scored_as_pronunciation():
    rows = word_rows([W(0.0, 0.4, "middling", probability=0.31), W(0.5, 0.9, "mind")])
    assert rows[0]["unclear"] and not rows[1]["unclear"]
