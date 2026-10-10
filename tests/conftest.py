"""What every test shares: its own empty database, and nothing from the machine it runs on.

coach.config reads the developer's .env on import. A key in it once hid a crash that
only happened without one, and a real key in a test is a real request waiting to happen,
so every variable the app reads is cleared for each test.
"""

import json

import pytest

from coach import backends, coach, config, llm, machine, relay, store

READ_FROM_ENVIRONMENT = (
    "GEMINI_API_KEY", "LM_STUDIO_URL", "COACH_BACKEND",
    "RELAY_URL", "RELAY_API_KEY", "RELAY_APP", "RELAY_USER", "RELAY_ADMIN",
)  # fmt: skip

# The machine every test runs on, whatever it really runs on: an 18GB M3 Pro.
MACHINE = {
    "cpu": "Apple M3 Pro", "cores": 11, "ram_gb": 18, "unified": True,
    "gpu": {"name": "Apple M3 Pro", "gb": 0, "cores": 14}, "model_gb": 12,
}  # fmt: skip
# A scored answer, as fluency() would hand it to the store.
METRICS = {"words": 40, "wpm": 120, "fillers": 1, "pauses": 2, "longest_pause": 1, "lead_in": 1}
# The coach's summary of a session: what reaches Telegram as its lessons.
LESSONS = {
    "work_on": ["past tense"],
    "phrases": [{"phrase": "a breath of fresh air", "meaning": "something new and pleasant"}],
    "instead_of_um": ["Let me think"],
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    for name in READ_FROM_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "API_KEY", "")
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "RECORDINGS", tmp_path / "recordings")
    # Connected lazily, by whichever thread asks first: the e2e server's own thread there.
    store._db = None
    coach._pending.clear()
    coach.failed.clear()
    llm._clients.clear()  # a client belongs to the event loop that first used it
    monkeypatch.setattr(llm, "waiting", "")
    # A developer's LM Studio would otherwise stand in for every model a test fails.
    monkeypatch.setattr(backends, "lm_studio_models", lambda _timeout=1.5: set())
    monkeypatch.setattr(machine, "specs", lambda: MACHINE)
    yield
    store._db = None


@pytest.fixture
def backdate():
    """Move a session's start back, as if it had run that long: a session has to last
    two minutes to count."""

    def move(session: int, minutes: int = 5) -> None:
        store.db().execute(
            "UPDATE sessions SET started_at = datetime(started_at, ?) WHERE id = ?",
            (f"-{minutes} minutes", session),
        )
        store.db().commit()

    return move


@pytest.fixture
def counted(backdate):
    """A session that counts: `answers` answers with `metrics`, started five minutes ago."""

    def make(mode: str = "talk", answers: int = 2, metrics: dict = METRICS, **start) -> int:
        session = store.start(mode, start.pop("backend", "flash-lite"), "m", **start)
        for n in range(answers):
            store.record(session, "interviewer", f"Question {n}?")
            store.record(session, "you", f"Answer number {n}.", metrics)
        backdate(session)
        return session

    return make


@pytest.fixture
def lessons():
    """Give a session the coach's summary, as if the coach had finished with it."""

    def attach(session: int) -> dict:
        store.db().execute(
            "UPDATE sessions SET summary = ? WHERE id = ?", (json.dumps(LESSONS), session)
        )
        store.db().commit()
        return LESSONS

    return attach


class FakeRelay:
    """Takes the place of the one function that talks to Relay, and keeps what was sent."""

    def __init__(self):
        self.sent: list[dict] = []
        self.takes_files = True  # an older Relay refuses the file block

    def __call__(self, method, _path, body=None):
        assert method == "POST", "nothing is ever read back from Relay"
        if not self.takes_files and any(b["type"] == "file" for b in body["blocks"]):
            raise RuntimeError("relay 422 invalid_request blocks[0].type: unknown")
        self.sent.append(body)
        return {"id": f"msg_{len(self.sent)}", "status": "queued"}


@pytest.fixture
def telegram(monkeypatch):
    """Relay switched on, and faked: never a real request from a test."""
    monkeypatch.setenv("RELAY_URL", "https://relay.test")
    monkeypatch.setenv("RELAY_API_KEY", "rk_test")
    monkeypatch.setenv("RELAY_APP", "coach")
    fake = FakeRelay()
    monkeypatch.setattr(relay, "_call", fake)
    return fake
