"""What the modes say and hear: chunking a reply for speech, routing a panel's voices, and
the arithmetic behind shadow and repeat."""

import asyncio

import pytest

from coach import llm, picture, profile, settings, store, tts
from coach.chunks import split_for_speech, split_speaker, take_budget
from coach.modes import _budget as budget
from coach.modes import interview, repeat, shadow, talk
from coach.modes._converse import cut_off
from coach.modes.panel import PANEL, VOICES
from coach.server.session import ACCENTS, Answer


def stream(tokens):
    """Feed tokens the way a model really sends them: several words at a time."""
    buffer, spoken = "", []
    for token in tokens:
        buffer += token
        speak, buffer = split_for_speech(buffer)
        if speak:
            spoken.append(speak)
    tail, _ = split_for_speech(buffer, flush=True)
    if tail:
        spoken.append(tail)
    return spoken


def test_a_sentence_ending_mid_token_is_still_found():
    """Splitting only when the buffer *ended* on a boundary cut sentences in half."""
    spoken = stream(
        [
            "That sounds",
            " like a really",
            " critical piece of the system to",
            " own. Walk me",
            " through how you handled two requests in the same millisecond?",
        ]
    )
    assert spoken == [
        "That sounds like a really critical piece of the system to own.",
        "Walk me through how you handled two requests in the same millisecond?",
    ]
    assert all(chunk[-1] in ".!?…" for chunk in spoken)


@pytest.mark.parametrize(
    ("tokens", "spoken"),
    [
        (["Hello. How are you? I am fine."], ["Hello. How are you? I am fine."]),
        (
            ["It costs 3.5 million", " and Dr. Chen signed", " it off."],
            ["It costs 3.5 million and Dr. Chen signed it off."],
        ),
        (["Half a sen"], ["Half a sen"]),  # flushed at the end of the stream
    ],
)
def test_decimals_and_titles_do_not_end_a_sentence(tokens, spoken):
    assert stream(tokens) == spoken


def test_nothing_is_spoken_before_a_boundary():
    assert split_for_speech("Half a sen") == ("", "Half a sen")
    assert split_for_speech("") == ("", "")


def test_a_run_on_breaks_between_words_never_inside_one():
    run_on = stream([w + " " for w in ["word"] * 90])
    assert len(run_on) > 1
    assert all(" " in c for c in run_on[:-1])
    assert not any(c.endswith("wor") or c.startswith("rd") for c in run_on)


def test_a_comma_never_ends_a_piece_of_speech():
    assert split_for_speech("Oh, nice one, getting home") == ("", "Oh, nice one, getting home")
    assert split_for_speech("Done. And then, more") == ("Done.", "And then, more")


@pytest.mark.parametrize(
    ("said", "heard", "score", "missed"),
    [
        ("I ended up staying in", "I ended up staying in", 1.0, []),
        ("I ended up staying in last night", "I end up staying last night", 0.71, ["ended", "in"]),
        ("", "anything", 0.0, []),
    ],
)
def test_shadow_matches_words_in_order(said, heard, score, missed):
    got, gone = shadow.match(said, heard)
    assert round(got, 2) == score
    assert gone == missed


def test_repeat_says_what_moved_from_the_first_telling_to_the_last():
    first, last = (
        {"wpm": 100, "fillers": 3.0, "pauses": 6.0},
        {"wpm": 118, "fillers": 2.9, "pauses": 4},
    )
    assert repeat.change(first, last) == (
        "From the first telling to the last: 18 wpm faster, 2.0 fewer pauses a minute."
    )
    assert repeat.change(first, first).startswith("About the same")
    assert len(repeat.table([first, last])) == 5
    assert repeat.table([first])[1][1] == "100"


@pytest.mark.parametrize(
    ("before", "now", "said"),
    [
        ({"wpm": 100}, {"wpm": 103}, []),  # under the threshold: noise
        ({"lead_in": 2.0}, {"lead_in": 1.0}, ["1.0s quicker to start"]),
        ({"fillers": 1.0}, {"fillers": 2.0}, ["1.0 more fillers per 100 words"]),
        ({"wpm": 100}, {}, []),  # nothing to compare with
    ],
)
def test_a_change_is_said_in_words_only_when_it_is_more_than_noise(before, now, said):
    assert picture.shifts(before, now) == said


@pytest.mark.parametrize(
    ("line", "routed"),
    [
        ("MAYA: Tell me about yourself.", ("MAYA", "Tell me about yourself.")),
        ("  DEREK:   Why Redis?", ("DEREK", "Why Redis?")),
        ("BOB: hello", (None, "hello")),  # unknown name, prefix still stripped
        ("Tell me about yourself.", (None, "Tell me about yourself.")),
    ],
)
def test_a_panel_line_goes_to_its_speakers_voice(line, routed):
    assert split_speaker(line, PANEL) == routed


def test_a_colon_mid_sentence_is_not_a_speaker():
    assert split_speaker("So the trade-off is: latency versus cost.", PANEL)[0] is None


def test_every_accent_talks_at_a_fluent_speakers_pace():
    """A different accent each session used to mean a different pace: 185 to 235 words a
    minute, so one session felt slow. The target is fixed - a learner never sets it by
    picking a slower voice."""
    assert set(ACCENTS) <= set(tts.PACE), "measure a new accent's pace before adding it"
    for chosen in ("am_puck", "am_michael"):
        settings.set("tts_voice", chosen)
        for voice in ACCENTS:
            assert round(tts.PACE[voice] * tts.pace(voice)) == tts.FLUENT
    assert tts.pace("not_a_measured_voice") == 1.0


class Overheard(Exception):  # noqa: N818 - control flow, not an error
    """Stops a mode at its first request to the model."""


class Ear:
    """Stands in for the browser just long enough to hear what a mode tells the model."""

    RETRY = "retry"

    def __init__(self, session: int = 0):
        self.session = session
        self.system = ""

    def prior_turns(self):
        return []

    async def send(self, **_event):
        pass

    async def reply(self, _endpoint, messages, **_how):
        self.system = messages[0]["content"]
        raise Overheard


def overhear(mode, session: int = 0) -> str:
    """The system prompt a mode opens with."""
    ear = Ear(session)
    with pytest.raises(Overheard):
        asyncio.run(mode.run(None, ear))
    return ear.system


def test_shadow_is_everyday_english_not_an_interview():
    """It was given the interview profile, and with it would have been given the resume."""
    profile.save({"role": "Backend engineer", "resume": "Payments at Acme."})
    heard = overhear(shadow)
    assert "Acme" not in heard
    assert "interviewing" not in heard


@pytest.mark.parametrize(("goal", "length"), [(20, 20), (None, interview.MINUTES)])
def test_the_interviewer_keeps_to_the_sessions_time(goal, length):
    session = store.start("interview", "flash-lite", "m", goal)
    assert interview.clock(session) == f"\n\nTime: 0 minutes into a {length}-minute interview."


def test_the_interviewer_has_your_resume_and_the_time():
    profile.save({"resume": "Payments at Acme."})
    heard = overhear(interview, store.start("interview", "flash-lite", "m", 30))
    assert "<resume>\nPayments at Acme.\n</resume>" in heard
    assert "Time: 0 minutes into a 30-minute interview." in heard


def test_every_panel_voice_speaks_at_a_fluent_speakers_pace():
    """af_nicole was not in PACE, so it played at its own pace: about 60% of the others'."""
    assert set(VOICES.values()) <= set(tts.PACE)


class Waiting(Ear):
    """Resumed on the user's turn: records what the page is told before the mic opens."""

    def __init__(self):
        super().__init__()
        self.events: list[dict] = []

    def prior_turns(self):
        return [{"role": "assistant", "content": "Tell me about yourself."}]

    async def send(self, **event):
        self.events.append(event)

    async def answer(self):
        raise Overheard


def wait_on(mode) -> "Waiting":
    """Run a mode until it opens the mic, and return what the page was told."""
    ear = Waiting()
    with pytest.raises(Overheard):
        asyncio.run(mode.run(None, ear))
    return ear


class Asking(Waiting):
    """A fresh interview: hears the interviewer's first question, then stops at the mic."""

    def __init__(self, question):
        super().__init__()
        self.question = question
        self.session = store.start("interview", "flash-lite", "m", 30)

    def prior_turns(self):
        return []

    async def reply(self, _endpoint, messages, **_how):
        self.system = messages[0]["content"]
        return llm.Reply("Tell me about yourself.", 1.0, self.question)


def countdown(mode, question) -> int | None:
    ear = Asking(question)
    with pytest.raises(Overheard):
        asyncio.run(mode.run(None, ear))
    sent = [e["seconds"] for e in ear.events if e.get("type") == "limit"]
    return sent[0] if sent else None


def test_the_interviewer_sizes_the_countdown_to_its_question():
    settings.set("answer_limit", 300)
    assert countdown(interview, 60) == 60
    assert countdown(interview, None) == 300  # no tag: the ceiling


def test_talk_has_no_countdown_and_is_never_asked_for_one():
    assert countdown(talk, 60) is None
    assert "square brackets" not in overhear(talk)
    assert "square brackets" in overhear(interview, store.start("interview", "flash-lite", "m", 30))


@pytest.mark.parametrize(
    ("asked", "ceiling", "seconds"),
    [(240, 300, 240), (900, 300, 300), (3, 300, budget.SHORTEST), (None, 120, 120), (60, 0, 0)],
)
def test_the_budget_stays_within_bounds(asked, ceiling, seconds):
    settings.set("answer_limit", ceiling)
    assert budget.seconds(asked, True) == seconds


@pytest.mark.parametrize(
    ("chunk", "taken"),
    [
        ("[60] Tell me about yourself.", (60, "Tell me about yourself.")),
        ("[240s] MAYA: Design a URL shortener.", (240, "MAYA: Design a URL shortener.")),
        ("What did you do? [90]", (90, "What did you do?")),
        ("[45]", (45, "")),  # the tag alone in the last piece: nothing left to speak
        ("Nice. Why Redis?", (None, "Nice. Why Redis?")),
    ],
)
def test_the_budget_tag_is_never_spoken(chunk, taken):
    assert take_budget(chunk) == taken


@pytest.mark.parametrize(
    ("seconds", "limit", "stopped"),
    [(45.2, 45, True), (44.3, 45, True), (30.0, 45, False), (60.0, 0, False)],
)
def test_the_interviewer_is_told_only_when_the_clock_ended_the_answer(seconds, limit, stopped):
    """A real interviewer who stops a long answer asks for it in one sentence."""
    note = cut_off(Answer("So the problem was", None, seconds), limit)
    assert ("Let me stop you there" in note) is stopped
