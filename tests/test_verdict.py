"""An interview's verdict: what the interviewer would submit, and who gets one."""

import asyncio
import json

import pytest

from coach import coach, history, llm, profile, store, verdict

WRITTEN = {
    "rating": "7",
    "decision": "Yes",
    "level": "mid-level",
    "scores": {"technical depth": 8, "communication": "6", "made up": "lots"},
    "summary": "Knew the payments system cold.",
}


def answered(monkeypatch, text: str) -> dict:
    """Stand in for the model; keep what it was asked."""
    asked: dict = {}

    async def model(_ep, messages, **_budget):
        asked["messages"] = messages
        return llm.Reply(text, 900.0)

    monkeypatch.setattr(llm, "patiently", model)
    return asked


def stored(session: int) -> dict | None:
    found = history.detail(session)
    assert found is not None
    return found["verdict"]


def test_a_verdict_needs_a_rating_out_of_ten_and_a_decision_on_the_scale():
    kept = verdict.valid(WRITTEN)
    assert kept is not None
    assert kept["rating"] == 7
    assert kept["scores"] == {"technical depth": 8, "communication": 6}
    assert verdict.valid({**WRITTEN, "rating": 11}) is None
    assert verdict.valid({**WRITTEN, "rating": "great"}) is None
    assert verdict.valid({**WRITTEN, "decision": "Strong hire"}) is None
    assert verdict.valid(None) is None
    assert verdict.headline(kept) == "7/10 · Yes"


def test_the_interviewer_judges_the_interview_against_the_resume(counted, monkeypatch):
    session = counted("interview", answers=3)
    profile.save({"resume": "Payments at Acme.", "job": "Globex hires Go engineers."})
    asked = answered(monkeypatch, "Here you go: " + json.dumps(WRITTEN))
    asyncio.run(verdict.write(session))
    told = asked["messages"][1]["content"]
    assert told.startswith("<resume>\nPayments at Acme.\n</resume>\n\n<job>\nGlobex")
    assert "INTERVIEWER: Question 0?\nCANDIDATE: Answer number 0." in told
    kept = stored(session)
    assert kept is not None
    assert (kept["rating"], kept["decision"], kept["answers"]) == (7, "Yes", 3)


def test_a_malformed_verdict_is_reported_not_kept(counted, monkeypatch):
    session = counted("panel")
    answered(monkeypatch, "I would probably hire them.")
    with pytest.raises(RuntimeError, match="malformed"):
        asyncio.run(verdict.write(session))
    assert stored(session) is None


@pytest.mark.parametrize(
    ("mode", "answers", "queued"),
    [
        ("interview", 2, True),
        ("panel", 2, True),
        ("review", 2, True),
        ("talk", 2, False),  # not an interview
        ("interview", 1, False),  # too short to count
    ],
)
def test_only_an_interview_that_counts_gets_a_verdict(counted, monkeypatch, mode, answers, queued):
    session = counted(mode, answers=answers)

    async def write(_session):
        pass

    monkeypatch.setattr(verdict, "write", write)

    async def ask():
        verdict.later(session)
        return coach.pending(session)

    assert asyncio.run(ask()) is queued


def test_a_verdict_is_written_once_unless_the_interview_went_on(counted, monkeypatch):
    session = counted("interview")
    answered(monkeypatch, json.dumps(WRITTEN))
    asyncio.run(verdict.write(session))

    async def ask():
        verdict.later(session)
        return coach.pending(session)

    assert asyncio.run(ask()) is False
    store.record(session, "you", "One more answer.")
    assert asyncio.run(ask()) is True
