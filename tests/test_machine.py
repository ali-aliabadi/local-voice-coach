"""This computer, and which local models it can hold."""

from coach import backends, machine

READ = machine.specs  # the real one: conftest swaps it for a fixed machine in every test

EVERY_LOCAL = {b.model for b in backends.CATALOGUE if b.local}


def test_the_machine_is_read():
    found = READ()
    assert found["cpu"]
    assert found["cores"] > 0
    assert 0 <= found["model_gb"] < found["ram_gb"]


def small_machine(monkeypatch, room: int = 4) -> None:
    monkeypatch.setattr(machine, "specs", lambda: {"model_gb": room})
    monkeypatch.setattr(backends, "lm_studio_models", lambda _timeout=1.5: EVERY_LOCAL)


def test_a_model_too_big_is_offered_greyed_out_and_says_why(monkeypatch):
    small_machine(monkeypatch)
    rows, _ = backends.survey("deep")
    why = {backend.key: reason for backend, reason in rows}
    assert why["gpt-oss-20b"] == "needs 12GB, this machine can spare 4GB"
    assert why["bonsai27"] is None, "loaded, and it fits"


def test_a_model_too_big_never_stands_in(monkeypatch):
    small_machine(monkeypatch)
    assert backends.stand_in() is backends.BY_KEY["bonsai27"]
    small_machine(monkeypatch, room=1)
    assert backends.stand_in() is backends.BY_KEY["lfm2.5"], "the only one that fits"
    small_machine(monkeypatch, room=0)
    assert backends.stand_in() is None


def test_settings_offer_what_fits_and_keep_what_was_chosen(monkeypatch):
    small_machine(monkeypatch)
    offered = backends.choices("qwen3.5-9b")
    assert "flash" in offered, "a cloud model fits anywhere"
    assert "qwen3.5-9b" in offered, "chosen before: a select must still show it"
    assert "gpt-oss-20b" not in offered
