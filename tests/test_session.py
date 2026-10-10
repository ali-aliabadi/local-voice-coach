"""Hearing an answer over the socket: what the page sends, and what it is scored as."""

import asyncio
import json

import numpy as np
import pytest

from coach import settings, store
from coach.server.session import Answer, BrowserIO

ANSWER = (np.zeros(16000, np.float32).tobytes(), {"type": "end_answer"})  # a second of it


class Page:
    """The browser's side of the socket: what it sends, in order, and what came back."""

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.events: list[dict] = []

    def says(self, *messages: bytes | dict) -> None:
        for m in messages:
            body = {"bytes": m} if isinstance(m, bytes) else {"text": json.dumps(m)}
            self.messages.append({"type": "websocket.receive", **body})

    async def receive(self) -> dict:
        return self.messages.pop(0)

    async def send_text(self, text: str) -> None:
        self.events.append(json.loads(text))


class Whisper:
    """Hears a first word half a second into whatever it is given."""

    async def transcribe(self, _audio):
        metrics = {"words": 3, "wpm": 120, "fillers": 0, "pauses": 0, "longest_pause": 0}
        return "I think so", {**metrics, "lead_in": 0.5}, [], 10.0


@pytest.fixture
def page():
    settings.set("coach_backend", "off")  # no notes written in the background
    return Page()


def lead_in(io: BrowserIO) -> float:
    answer = asyncio.run(io.answer())
    assert isinstance(answer, Answer)
    assert answer.metrics
    return answer.metrics["lead_in"]


def listening(page: Page) -> BrowserIO:
    session = store.start("talk", "flash-lite", "m")
    return BrowserIO(page, None, Whisper(), session)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("began", "expected"),
    [
        ([], 0.5),  # space: the recording starts when you press, Whisper's timing stands
        ([{"type": "began", "after": 2.0}], 2.5),  # hybrid: two quiet seconds, then a half
        ([{"type": "began", "after": -1.0}], 0.0),  # cut in: they were still talking
    ],
)
def test_before_you_spoke_counts_from_the_end_of_their_sentence(page, began, expected):
    """In hybrid the recording starts on your voice, not when the partner stopped: the
    page says how far apart those were, and Whisper times the first word from there."""
    page.says(*began, *ANSWER)
    assert lead_in(listening(page)) == expected


def test_each_answer_starts_without_the_last_ones_offset(page):
    io = listening(page)
    page.says({"type": "began", "after": 2.0}, *ANSWER)
    lead_in(io)
    page.says(*ANSWER)  # pressed space this time
    assert lead_in(io) == 0.5
