"""The study sheet: written by a model, drawn as pages with Pillow, sent as a PDF."""

import asyncio
import json

import pytest

from coach import config, layout, llm, reports, settings, sheet

WRITTEN = {
    "title": "A good session",
    "went_well": "You told a clear story — well done.",
    "fixes": [{"said": "with me and my wife", "better": "with my wife and me", "why": "polite"}],
    "phrases": [
        {
            "phrase": "not really my thing",
            "meaning": "I don't like it",
            "instead_of": "I don't like cinema",
            "example": "Cinemas are not my thing.",
        }
    ],
    "instead_of_um": ["Let me think…"],
    "practice": ["Retell the film in 60 seconds."] * 3,
}
TIMED = {"total": 3000, "hearing": 1000, "thinking": 1500, "voicing": 500}


@pytest.fixture
def written(monkeypatch, counted):
    """A session of four answers whose sheet a faked model has written."""

    async def model(_ep, messages, max_tokens=None):  # noqa: ARG001 - the real signature
        assert "study sheet" in messages[0]["content"] and "LEARNER:" in messages[1]["content"]
        return llm.Reply(json.dumps(WRITTEN), 1.0)

    monkeypatch.setattr(llm, "patiently", model)  # the one call that reaches a model
    session = counted(answers=4)
    asyncio.run(sheet.write(session))
    return session


def test_the_sheet_is_written_and_drawn(written):
    assert sheet.stored(written)["title"] == "A good session"
    doc = sheet.render(written)
    assert doc.pdf()[:4] == b"%PDF" and len(doc.pngs()) >= 1
    assert len(doc.pages) >= 2, "the session's answers, charted at the end"


def test_time_on_the_sheet_is_only_what_was_measured():
    detail = {
        "minutes": 34.2,
        "goal_minutes": 30,
        "averages": {"spoken": 14.6},
        "turns": [{"timing": TIMED}, {"timing": None}, {"timing": {**TIMED, "total": 5000}}],
        "listening": {"replies": 20, "helped": 3},
    }
    tiles = sheet._time_tiles(detail)
    assert tiles[0] == ("34 min", "session", "goal 30 min, reached", True)
    assert tiles[1][0] == "15 min" and tiles[1][2] == "43% of the session"
    assert tiles[2][0] == "4.0s", "the mean of the two timed replies"
    assert tiles[3][0] == "17/20"


def test_nothing_is_invented_for_what_was_not_measured():
    bare = sheet._time_tiles({"minutes": 12, "goal_minutes": None, "averages": {}, "turns": []})
    assert bare == [("12 min", "session", "start to last answer", None)]


def test_the_sheet_goes_as_a_pdf_and_carries_the_lessons(telegram, written, lessons):
    lessons(written)
    asyncio.run(reports.after_session(written))
    session_report, pdf = telegram.sent
    # Relay's recipe for a file: a line saying what it is, then the file
    assert [b["type"] for b in pdf["blocks"]] == ["text", "file"]
    assert pdf["blocks"][1]["filename"].endswith(".pdf")
    assert pdf["blocks"][1]["content_type"] == "application/pdf"
    assert "breath of fresh air" not in json.dumps(session_report), "the sheet has them"


def test_an_older_relay_gets_the_pages_as_images(telegram, written):
    telegram.takes_files = False
    asyncio.run(reports.after_session(written))
    assert telegram.sent[-1]["blocks"][0]["type"] == "image"


def test_no_sheet_on_telegram_when_it_is_switched_off(telegram, written):
    settings.set("relay_sheet", "off")
    asyncio.run(reports.after_session(written))
    assert len(telegram.sent) == 1


def test_long_text_runs_onto_another_page():
    doc = layout.Doc()
    for _ in range(80):
        doc.text("A long line about cinemas, small talk and leftovers — again and again. " * 2)
    assert len(doc.pages) >= 2 and doc.pdf()[:4] == b"%PDF"


def test_without_the_font_it_still_renders_in_plain_ascii(monkeypatch):
    monkeypatch.setattr(config, "REPORT_FONT", "/nowhere/Inter.ttf")
    plain = layout.Doc()
    assert plain.plain and plain.clean("café → “ok” — fine") == 'cafe -> "ok" - fine'
    assert plain.pdf()[:4] == b"%PDF"
